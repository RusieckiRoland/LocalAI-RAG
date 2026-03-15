from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from code_query_engine.conversation_history.ports import IUserConversationStore
from code_query_engine.conversation_history.types import ConversationTurn


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_visible_session_id(session_id: str) -> str:
    sid = str(session_id or "").strip()
    if sid.startswith("u_") and "__" in sid:
        return sid.split("__", 1)[1].strip() or sid
    return sid


def _safe_tenant_id(value: str) -> str:
    out = str(value or "").strip() or "tenant-default"
    return out[:36]


def _safe_user_id(value: str) -> str:
    out = str(value or "").strip() or "anon"
    return out[:80]


def _safe_session_id(value: str) -> str:
    out = _normalize_visible_session_id(value)
    out = str(out or "").strip() or uuid.uuid4().hex
    return out[:36]


def _safe_message_id(value: str) -> str:
    out = str(value or "").strip() or uuid.uuid4().hex
    return out[:36]


def _dt_to_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return int(float(raw))
        except Exception:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except Exception:
                return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    return None


def _loads_meta(raw: Any) -> Any:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _dumps_meta(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps({"raw": str(value)}, ensure_ascii=False, sort_keys=True)


class SqlChatHistoryStore:
    def __init__(
        self,
        *,
        database_type: str,
        connection_url: str,
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._database_type = str(database_type or "").strip().lower()
        self._connection_url = str(connection_url or "").strip()
        self._connect_timeout_seconds = max(1, int(connect_timeout_seconds or 5))
        self._engine_instance = None
        if self._database_type not in {"postgres", "mysql", "mssql"}:
            raise ValueError("SqlChatHistoryStore requires database_type in {'postgres','mysql','mssql'}")
        if not self._connection_url:
            raise ValueError("SqlChatHistoryStore requires a non-empty connection_url")

    def list_sessions(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int,
        cursor: Optional[str],
        q: Optional[str],
    ) -> dict:
        from sqlalchemy import text  # type: ignore

        tenant_id = _safe_tenant_id(tenant_id)
        user_id = _safe_user_id(user_id)
        lim = max(1, min(200, int(limit or 50)))
        qn = str(q or "").strip().lower()
        with self._engine().connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT
                      s.id AS session_id,
                      s.tenant_id AS tenant_id,
                      s.user_id AS user_id,
                      s.title AS title,
                      s.consultant_id AS consultant_id,
                      s.message_count AS message_count,
                      s.created_at AS created_at,
                      s.updated_at AS updated_at,
                      s.deleted_at AS deleted_at,
                      CASE WHEN EXISTS (
                        SELECT 1
                        FROM {self._tn('chat_session_tags')} st
                        JOIN {self._tn('chat_tags')} t ON t.id = st.tag_id
                        WHERE st.session_id = s.id
                          AND st.tenant_id = s.tenant_id
                          AND t.name = :important_tag
                      ) THEN 1 ELSE 0 END AS important
                    FROM {self._tn('chat_sessions')} s
                    WHERE s.tenant_id = :tenant_id
                      AND s.user_id = :user_id
                      AND s.deleted_at IS NULL
                    ORDER BY s.updated_at DESC, s.id DESC
                    """
                ),
                {"tenant_id": tenant_id, "user_id": user_id, "important_tag": "important"},
            ).mappings().all()

        items = [self._session_payload(row) for row in rows]
        if qn:
            items = [item for item in items if qn in str(item.get("title") or "").lower()]

        start_idx = 0
        cur = str(cursor or "").strip()
        if cur:
            for idx, item in enumerate(items):
                if str(item.get("updatedAt")) == cur:
                    start_idx = idx + 1
                    break
        sliced = items[start_idx : start_idx + lim]
        next_cursor = str(sliced[-1]["updatedAt"]) if len(sliced) == lim else None
        return {"items": sliced, "next_cursor": next_cursor}

    def create_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        title: str,
        consultant_id: str,
    ) -> dict:
        from sqlalchemy import text  # type: ignore

        tenant_id = _safe_tenant_id(tenant_id)
        user_id = _safe_user_id(user_id)
        session_id = _safe_session_id(session_id)
        now = _utcnow()
        with self._engine().begin() as conn:
            self._ensure_tenant(conn, tenant_id=tenant_id)
            existing = self._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                include_deleted=True,
            )
            if existing is None:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._tn('chat_sessions')}
                          (id, tenant_id, user_id, title, consultant_id, message_count, created_at, updated_at, deleted_at, deleted_by)
                        VALUES
                          (:id, :tenant_id, :user_id, :title, :consultant_id, :message_count, :created_at, :updated_at, :deleted_at, :deleted_by)
                        """
                    ),
                    {
                        "id": session_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "title": str(title or "New chat")[:200],
                        "consultant_id": str(consultant_id or "")[:80] or None,
                        "message_count": 0,
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                        "deleted_by": None,
                    },
                )
            else:
                updates: Dict[str, Any] = {"id": session_id, "tenant_id": tenant_id, "user_id": user_id, "updated_at": now}
                set_parts = ["updated_at = :updated_at", "deleted_at = NULL", "deleted_by = NULL"]
                current_title = str(existing.get("title") or "").strip()
                new_title = str(title or "").strip()
                if new_title and ((not current_title) or current_title.lower() in ("new chat", "nowy czat")):
                    updates["title"] = new_title[:200]
                    set_parts.append("title = :title")
                new_consultant = str(consultant_id or "").strip()
                if new_consultant and not str(existing.get("consultant_id") or "").strip():
                    updates["consultant_id"] = new_consultant[:80]
                    set_parts.append("consultant_id = :consultant_id")
                conn.execute(
                    text(
                        f"""
                        UPDATE {self._tn('chat_sessions')}
                        SET {", ".join(set_parts)}
                        WHERE id = :id AND tenant_id = :tenant_id AND user_id = :user_id
                        """
                    ),
                    updates,
                )
            row = self._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                include_deleted=True,
            )
            if row is None:
                raise RuntimeError("Failed to create SQL chat session.")
            return self._session_payload(row)

    def get_session(self, *, tenant_id: str, user_id: str, session_id: str) -> Optional[dict]:
        tenant_id = _safe_tenant_id(tenant_id)
        user_id = _safe_user_id(user_id)
        session_id = _safe_session_id(session_id)
        with self._engine().connect() as conn:
            row = self._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                include_deleted=False,
            )
            if row is None:
                return None
            return self._session_payload(row)

    def patch_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        payload: dict,
    ) -> Optional[dict]:
        from sqlalchemy import text  # type: ignore

        tenant_id = _safe_tenant_id(tenant_id)
        user_id = _safe_user_id(user_id)
        session_id = _safe_session_id(session_id)
        now = _utcnow()
        with self._engine().begin() as conn:
            existing = self._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                include_deleted=True,
            )
            if existing is None or _dt_to_ms(existing.get("deleted_at")) is not None:
                return None

            updates: Dict[str, Any] = {
                "id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "updated_at": now,
            }
            set_parts = ["updated_at = :updated_at"]
            if "title" in payload and payload.get("title") is not None:
                updates["title"] = str(payload.get("title") or "")[:200]
                set_parts.append("title = :title")
            if "consultantId" in payload and payload.get("consultantId") is not None:
                updates["consultant_id"] = str(payload.get("consultantId") or "")[:80] or None
                set_parts.append("consultant_id = :consultant_id")
            if "softDeleted" in payload:
                if bool(payload.get("softDeleted")):
                    updates["deleted_at"] = now
                    set_parts.append("deleted_at = :deleted_at")
                else:
                    set_parts.append("deleted_at = NULL")
            conn.execute(
                text(
                    f"""
                    UPDATE {self._tn('chat_sessions')}
                    SET {", ".join(set_parts)}
                    WHERE id = :id AND tenant_id = :tenant_id AND user_id = :user_id
                    """
                ),
                updates,
            )

            if "important" in payload:
                if bool(payload.get("important")):
                    self._set_important(conn, tenant_id=tenant_id, session_id=session_id, enabled=True)
                else:
                    self._set_important(conn, tenant_id=tenant_id, session_id=session_id, enabled=False)

            row = self._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                include_deleted=True,
            )
            if row is None:
                return None
            return self._session_payload(row)

    def list_messages(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        limit: int,
        before: Optional[str],
    ) -> Optional[dict]:
        from sqlalchemy import text  # type: ignore

        tenant_id = _safe_tenant_id(tenant_id)
        user_id = _safe_user_id(user_id)
        session_id = _safe_session_id(session_id)
        before_ms = _dt_to_ms(before)
        lim = max(1, min(200, int(limit or 100)))
        with self._engine().connect() as conn:
            existing = self._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                include_deleted=True,
            )
            if existing is None:
                return None
            rows = conn.execute(
                text(
                    f"""
                    SELECT
                      id AS message_id,
                      session_id AS session_id,
                      ts AS ts,
                      q AS q,
                      a AS a,
                      meta_json AS meta_json,
                      deleted_at AS deleted_at
                    FROM {self._tn('chat_messages')}
                    WHERE session_id = :session_id
                      AND tenant_id = :tenant_id
                      AND deleted_at IS NULL
                    ORDER BY ts ASC, id ASC
                    """
                ),
                {"session_id": session_id, "tenant_id": tenant_id},
            ).mappings().all()

        items = [self._message_payload(row) for row in rows]
        if before_ms is not None:
            items = [item for item in items if int(item.get("ts") or 0) < before_ms]
        sliced = items[-lim:]
        next_cursor = str(sliced[0]["ts"]) if len(sliced) == lim else None
        return {"items": sliced, "next_cursor": next_cursor}

    def add_message(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        message_id: str,
        q: str,
        a: str,
        meta: Any,
    ) -> dict:
        from sqlalchemy import text  # type: ignore

        tenant_id = _safe_tenant_id(tenant_id)
        user_id = _safe_user_id(user_id)
        session_id = _safe_session_id(session_id)
        message_id = _safe_message_id(message_id)
        now = _utcnow()
        with self._engine().begin() as conn:
            self._ensure_tenant(conn, tenant_id=tenant_id)
            session = self._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                include_deleted=True,
            )
            if session is None:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._tn('chat_sessions')}
                          (id, tenant_id, user_id, title, consultant_id, message_count, created_at, updated_at, deleted_at, deleted_by)
                        VALUES
                          (:id, :tenant_id, :user_id, :title, :consultant_id, :message_count, :created_at, :updated_at, :deleted_at, :deleted_by)
                        """
                    ),
                    {
                        "id": session_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "title": "New chat",
                        "consultant_id": "",
                        "message_count": 0,
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                        "deleted_by": None,
                    },
                )
            existing_message = conn.execute(
                text(
                    f"""
                    SELECT
                      id AS message_id,
                      session_id AS session_id,
                      ts AS ts,
                      q AS q,
                      a AS a,
                      meta_json AS meta_json,
                      deleted_at AS deleted_at
                    FROM {self._tn('chat_messages')}
                    WHERE id = :id AND session_id = :session_id AND tenant_id = :tenant_id
                    """
                ),
                {"id": message_id, "session_id": session_id, "tenant_id": tenant_id},
            ).mappings().first()
            if existing_message is not None:
                return self._message_payload(existing_message)
            conn.execute(
                text(
                    f"""
                    INSERT INTO {self._tn('chat_messages')}
                      (id, session_id, tenant_id, ts, q, a, meta_json, deleted_at, deleted_by)
                    VALUES
                      (:id, :session_id, :tenant_id, :ts, :q, :a, :meta_json, :deleted_at, :deleted_by)
                    """
                ),
                {
                    "id": message_id,
                    "session_id": session_id,
                    "tenant_id": tenant_id,
                    "ts": now,
                    "q": str(q or ""),
                    "a": str(a or ""),
                    "meta_json": _dumps_meta(meta),
                    "deleted_at": None,
                    "deleted_by": None,
                },
            )
            title = str(q or "").replace("\n", " ").strip()[:64]
            self._touch_session_after_message(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                title_hint=title,
                now=now,
            )
            row = conn.execute(
                text(
                    f"""
                    SELECT
                      id AS message_id,
                      session_id AS session_id,
                      ts AS ts,
                      q AS q,
                      a AS a,
                      meta_json AS meta_json,
                      deleted_at AS deleted_at
                    FROM {self._tn('chat_messages')}
                    WHERE id = :id
                    """
                ),
                {"id": message_id},
            ).mappings().first()
            if row is None:
                raise RuntimeError("Failed to create SQL chat message.")
            return self._message_payload(row)

    def _touch_session_after_message(self, conn, *, tenant_id: str, user_id: str, session_id: str, title_hint: str, now: datetime) -> None:
        from sqlalchemy import text  # type: ignore

        count = int(
            conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM {self._tn('chat_messages')}
                    WHERE session_id = :session_id
                      AND tenant_id = :tenant_id
                      AND deleted_at IS NULL
                    """
                ),
                {"session_id": session_id, "tenant_id": tenant_id},
            ).scalar()
            or 0
        )
        session = self._get_session_row(
            conn,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            include_deleted=True,
        )
        title_current = str((session or {}).get("title") or "").strip().lower()
        params: Dict[str, Any] = {
            "id": session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "message_count": count,
            "updated_at": now,
        }
        set_parts = ["message_count = :message_count", "updated_at = :updated_at"]
        if title_hint and (not title_current or title_current in ("new chat", "nowy czat")):
            params["title"] = title_hint[:200]
            set_parts.append("title = :title")
        conn.execute(
            text(
                f"""
                UPDATE {self._tn('chat_sessions')}
                SET {", ".join(set_parts)}
                WHERE id = :id AND tenant_id = :tenant_id AND user_id = :user_id
                """
            ),
            params,
        )

    def _set_important(self, conn, *, tenant_id: str, session_id: str, enabled: bool) -> None:
        from sqlalchemy import text  # type: ignore

        tag_name = "important"
        tag_id = conn.execute(
            text(
                f"""
                SELECT id
                FROM {self._tn('chat_tags')}
                WHERE tenant_id = :tenant_id AND name = :name
                """
            ),
            {"tenant_id": tenant_id, "name": tag_name},
        ).scalar()
        if enabled:
            if not tag_id:
                tag_id = uuid.uuid4().hex[:36]
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._tn('chat_tags')} (id, tenant_id, name, created_at)
                        VALUES (:id, :tenant_id, :name, :created_at)
                        """
                    ),
                    {"id": tag_id, "tenant_id": tenant_id, "name": tag_name, "created_at": _utcnow()},
                )
            exists = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM {self._tn('chat_session_tags')}
                    WHERE session_id = :session_id AND tag_id = :tag_id
                    """
                ),
                {"session_id": session_id, "tag_id": tag_id},
            ).scalar()
            if int(exists or 0) <= 0:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._tn('chat_session_tags')} (session_id, tag_id, tenant_id, created_at)
                        VALUES (:session_id, :tag_id, :tenant_id, :created_at)
                        """
                    ),
                    {
                        "session_id": session_id,
                        "tag_id": tag_id,
                        "tenant_id": tenant_id,
                        "created_at": _utcnow(),
                    },
                )
            return
        if tag_id:
            conn.execute(
                text(
                    f"""
                    DELETE FROM {self._tn('chat_session_tags')}
                    WHERE session_id = :session_id AND tag_id = :tag_id
                    """
                ),
                {"session_id": session_id, "tag_id": tag_id},
            )

    def _ensure_tenant(self, conn, *, tenant_id: str) -> None:
        from sqlalchemy import text  # type: ignore

        exists = conn.execute(
            text(f"SELECT COUNT(*) FROM {self._tn('chat_tenants')} WHERE id = :id"),
            {"id": tenant_id},
        ).scalar()
        if int(exists or 0) > 0:
            return
        conn.execute(
            text(
                f"""
                INSERT INTO {self._tn('chat_tenants')} (id, name, created_at)
                VALUES (:id, :name, :created_at)
                """
            ),
            {"id": tenant_id, "name": tenant_id, "created_at": _utcnow()},
        )

    def _get_session_row(self, conn, *, tenant_id: str, user_id: str, session_id: str, include_deleted: bool):
        from sqlalchemy import text  # type: ignore

        where_deleted = "" if include_deleted else "AND s.deleted_at IS NULL"
        return conn.execute(
            text(
                f"""
                SELECT
                  s.id AS session_id,
                  s.tenant_id AS tenant_id,
                  s.user_id AS user_id,
                  s.title AS title,
                  s.consultant_id AS consultant_id,
                  s.message_count AS message_count,
                  s.created_at AS created_at,
                  s.updated_at AS updated_at,
                  s.deleted_at AS deleted_at,
                  CASE WHEN EXISTS (
                    SELECT 1
                    FROM {self._tn('chat_session_tags')} st
                    JOIN {self._tn('chat_tags')} t ON t.id = st.tag_id
                    WHERE st.session_id = s.id
                      AND st.tenant_id = s.tenant_id
                      AND t.name = :important_tag
                  ) THEN 1 ELSE 0 END AS important
                FROM {self._tn('chat_sessions')} s
                WHERE s.id = :session_id
                  AND s.tenant_id = :tenant_id
                  AND s.user_id = :user_id
                  {where_deleted}
                """
            ),
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "important_tag": "important",
            },
        ).mappings().first()

    def _session_payload(self, row) -> dict:
        soft_deleted_at = _dt_to_ms(row.get("deleted_at"))
        return {
            "sessionId": str(row.get("session_id") or ""),
            "tenantId": str(row.get("tenant_id") or ""),
            "userId": str(row.get("user_id") or ""),
            "title": str(row.get("title") or "New chat"),
            "consultantId": str(row.get("consultant_id") or ""),
            "createdAt": _dt_to_ms(row.get("created_at")) or 0,
            "updatedAt": _dt_to_ms(row.get("updated_at")) or 0,
            "messageCount": int(row.get("message_count") or 0),
            "deletedAt": None,
            "softDeletedAt": soft_deleted_at,
            "status": "soft_deleted" if soft_deleted_at is not None else "active",
            "important": bool(int(row.get("important") or 0)),
        }

    def _message_payload(self, row) -> dict:
        return {
            "messageId": str(row.get("message_id") or ""),
            "sessionId": str(row.get("session_id") or ""),
            "ts": _dt_to_ms(row.get("ts")) or 0,
            "q": "" if row.get("q") is None else str(row.get("q")),
            "a": "" if row.get("a") is None else str(row.get("a")),
            "meta": _loads_meta(row.get("meta_json")),
            "deletedAt": _dt_to_ms(row.get("deleted_at")),
        }

    def _tn(self, table_name: str) -> str:
        if self._database_type == "mysql":
            return table_name
        return f"history.{table_name}"

    def _engine(self):
        from sqlalchemy import create_engine  # type: ignore

        if self._engine_instance is not None:
            return self._engine_instance
        connect_args = {}
        if self._database_type in {"postgres", "mysql"}:
            connect_args["connect_timeout"] = int(self._connect_timeout_seconds)
        elif self._database_type == "mssql":
            connect_args["timeout"] = int(self._connect_timeout_seconds)
        self._engine_instance = create_engine(self._connection_url, pool_pre_ping=True, connect_args=connect_args)
        return self._engine_instance


class SqlConversationHistoryStore(IUserConversationStore):
    def __init__(
        self,
        *,
        history_store: SqlChatHistoryStore,
        tenant_resolver: Callable[[], str],
        user_resolver: Callable[[], str],
    ) -> None:
        self._history_store = history_store
        self._tenant_resolver = tenant_resolver
        self._user_resolver = user_resolver

    def upsert_session_link(self, *, identity_id: str, session_id: str) -> None:
        tenant_id = _safe_tenant_id(self._tenant_resolver())
        user_id = _safe_user_id(identity_id or self._user_resolver())
        self._history_store.create_session(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=_normalize_visible_session_id(session_id),
            title="New chat",
            consultant_id="",
        )

    def insert_turn(self, *, turn: ConversationTurn) -> None:
        tenant_id = _safe_tenant_id(self._tenant_resolver())
        user_id = _safe_user_id(turn.identity_id or self._user_resolver())
        session_id = _normalize_visible_session_id(turn.session_id)
        self._history_store.add_message(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            message_id=turn.turn_id,
            q=turn.question_neutral or "",
            a=turn.answer_neutral or "",
            meta={
                "request_id": turn.request_id,
                "question_translated": turn.question_translated,
                "answer_translated": turn.answer_translated,
                "answer_translated_is_fallback": turn.answer_translated_is_fallback,
                "metadata": dict(turn.metadata or {}),
                "created_at_utc": turn.created_at_utc,
                "finalized_at_utc": turn.finalized_at_utc,
            },
        )

    def upsert_turn_final(
        self,
        *,
        identity_id: str,
        session_id: str,
        turn_id: str,
        answer_neutral: str,
        answer_translated: Optional[str],
        answer_translated_is_fallback: Optional[bool],
        finalized_at_utc: Optional[str],
        meta: Optional[dict[str, Any]],
    ) -> None:
        from sqlalchemy import text  # type: ignore

        tenant_id = _safe_tenant_id(self._tenant_resolver())
        user_id = _safe_user_id(identity_id or self._user_resolver())
        visible_session_id = _safe_session_id(session_id)
        msg_id = _safe_message_id(turn_id)
        now = _utcnow()
        engine = self._history_store._engine()
        with engine.begin() as conn:
            self._history_store._ensure_tenant(conn, tenant_id=tenant_id)
            session = self._history_store._get_session_row(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=visible_session_id,
                include_deleted=True,
            )
            if session is None:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._history_store._tn('chat_sessions')}
                          (id, tenant_id, user_id, title, consultant_id, message_count, created_at, updated_at, deleted_at, deleted_by)
                        VALUES
                          (:id, :tenant_id, :user_id, :title, :consultant_id, :message_count, :created_at, :updated_at, :deleted_at, :deleted_by)
                        """
                    ),
                    {
                        "id": visible_session_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "title": "New chat",
                        "consultant_id": "",
                        "message_count": 0,
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                        "deleted_by": None,
                    },
                )

            existing = conn.execute(
                text(
                    f"""
                    SELECT q, meta_json
                    FROM {self._history_store._tn('chat_messages')}
                    WHERE id = :id AND session_id = :session_id AND tenant_id = :tenant_id
                    """
                ),
                {"id": msg_id, "session_id": visible_session_id, "tenant_id": tenant_id},
            ).mappings().first()
            meta_payload = _loads_meta((existing or {}).get("meta_json")) or {}
            if not isinstance(meta_payload, dict):
                meta_payload = {"metadata": meta_payload}
            meta_payload["answer_translated"] = answer_translated
            meta_payload["answer_translated_is_fallback"] = answer_translated_is_fallback
            meta_payload["finalized_at_utc"] = finalized_at_utc
            if meta is not None:
                meta_payload["metadata"] = dict(meta)

            if existing is None:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._history_store._tn('chat_messages')}
                          (id, session_id, tenant_id, ts, q, a, meta_json, deleted_at, deleted_by)
                        VALUES
                          (:id, :session_id, :tenant_id, :ts, :q, :a, :meta_json, :deleted_at, :deleted_by)
                        """
                    ),
                    {
                        "id": msg_id,
                        "session_id": visible_session_id,
                        "tenant_id": tenant_id,
                        "ts": now,
                        "q": "",
                        "a": str(answer_neutral or ""),
                        "meta_json": _dumps_meta(meta_payload),
                        "deleted_at": None,
                        "deleted_by": None,
                    },
                )
            else:
                conn.execute(
                    text(
                        f"""
                        UPDATE {self._history_store._tn('chat_messages')}
                        SET a = :a,
                            meta_json = :meta_json
                        WHERE id = :id AND session_id = :session_id AND tenant_id = :tenant_id
                        """
                    ),
                    {
                        "a": str(answer_neutral or ""),
                        "meta_json": _dumps_meta(meta_payload),
                        "id": msg_id,
                        "session_id": visible_session_id,
                        "tenant_id": tenant_id,
                    },
                )
            title_hint = str((existing or {}).get("q") or "").replace("\n", " ").strip()[:64]
            self._history_store._touch_session_after_message(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=visible_session_id,
                title_hint=title_hint,
                now=now,
            )

    def list_recent_finalized_turns_by_session(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> List[ConversationTurn]:
        from sqlalchemy import text  # type: ignore

        visible_session_id = _safe_session_id(session_id)
        lim = max(1, int(limit or 20))
        tenant_id = _safe_tenant_id(self._tenant_resolver())
        user_id = _safe_user_id(self._user_resolver())
        engine = self._history_store._engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT
                      m.id AS message_id,
                      m.session_id AS session_id,
                      m.ts AS ts,
                      m.q AS q,
                      m.a AS a,
                      m.meta_json AS meta_json
                    FROM {self._history_store._tn('chat_messages')} m
                    JOIN {self._history_store._tn('chat_sessions')} s ON s.id = m.session_id
                    WHERE m.session_id = :session_id
                      AND s.tenant_id = :tenant_id
                      AND s.user_id = :user_id
                      AND m.deleted_at IS NULL
                      AND COALESCE(m.a, '') <> ''
                    ORDER BY m.ts DESC, m.id DESC
                    """
                ),
                {
                    "session_id": visible_session_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            ).mappings().all()

        rows = list(reversed(rows[:lim]))
        out: List[ConversationTurn] = []
        for row in rows:
            meta_payload = _loads_meta(row.get("meta_json")) or {}
            if not isinstance(meta_payload, dict):
                meta_payload = {}
            created_at = meta_payload.get("created_at_utc")
            if not created_at:
                ts_ms = _dt_to_ms(row.get("ts")) or 0
                created_at = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            metadata = meta_payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            out.append(
                ConversationTurn(
                    turn_id=str(row.get("message_id") or ""),
                    session_id=str(row.get("session_id") or ""),
                    request_id=str(meta_payload.get("request_id") or ""),
                    created_at_utc=str(created_at),
                    identity_id=user_id,
                    finalized_at_utc=str(meta_payload.get("finalized_at_utc") or "") or None,
                    question_neutral=str(row.get("q") or ""),
                    answer_neutral=str(row.get("a") or ""),
                    question_translated=(
                        str(meta_payload.get("question_translated")) if meta_payload.get("question_translated") is not None else None
                    ),
                    answer_translated=(
                        str(meta_payload.get("answer_translated")) if meta_payload.get("answer_translated") is not None else None
                    ),
                    answer_translated_is_fallback=(
                        bool(meta_payload.get("answer_translated_is_fallback"))
                        if meta_payload.get("answer_translated_is_fallback") is not None
                        else None
                    ),
                    metadata=metadata,
                )
            )
        return out
