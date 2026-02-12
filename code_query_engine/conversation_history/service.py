from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from .ports import IConversationHistoryService, ISessionConversationStore, IUserConversationStore
from .types import ConversationTurn


class ConversationHistoryService(IConversationHistoryService):
    def __init__(
        self,
        *,
        session_store: ISessionConversationStore,
        durable_store: Optional[IUserConversationStore] = None,
    ) -> None:
        self._session_store = session_store
        self._durable_store = durable_store
        self._session_to_identity: dict[str, str] = {}

    def _now_utc(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _ensure_session_identity_link(self, *, session_id: str, identity_id: str) -> None:
        sid = str(session_id or "").strip()
        iid = str(identity_id or "").strip()
        if not sid or not iid:
            return

        existing = self._session_to_identity.get(sid)
        if existing and existing != iid:
            raise ValueError(f"session_id already linked to a different identity_id (session_id={sid!r})")
        self._session_to_identity[sid] = iid

        if self._durable_store is not None:
            self._durable_store.upsert_session_link(identity_id=iid, session_id=sid)

    def on_request_started(
        self,
        *,
        session_id: str,
        request_id: str,
        identity_id: Optional[str],
        translate_chat: bool,
        question_neutral: str,
        question_translated: Optional[str],
        meta: Optional[dict[str, Any]] = None,
    ) -> str:
        sid = str(session_id or "").strip()
        rid = str(request_id or "").strip()
        if not rid:
            rid = str(uuid.uuid4())
        if not sid:
            raise ValueError("ConversationHistoryService.on_request_started: session_id is required")

        iid = str(identity_id or "").strip() or None
        if iid:
            self._ensure_session_identity_link(session_id=sid, identity_id=iid)

        turn_id = self._session_store.start_turn(
            session_id=sid,
            request_id=rid,
            identity_id=iid,
            question_neutral=str(question_neutral or ""),
            question_translated=question_translated,
            translate_chat=bool(translate_chat),
            meta=meta,
        )

        if self._durable_store is not None and iid:
            # Durable store expects a canonical record; store "started" turn as well (answer fields empty for now).
            self._durable_store.insert_turn(
                turn=ConversationTurn(
                    turn_id=turn_id,
                    session_id=sid,
                    request_id=rid,
                    created_at_utc=self._now_utc(),
                    identity_id=iid,
                    finalized_at_utc=None,
                    question_neutral=str(question_neutral or ""),
                    answer_neutral=None,
                    question_translated=question_translated,
                    answer_translated=None,
                    answer_translated_is_fallback=None,
                    metadata=dict(meta or {}),
                )
            )

        return turn_id

    def on_request_finalized(
        self,
        *,
        session_id: str,
        request_id: str,
        identity_id: Optional[str],
        turn_id: Optional[str],
        answer_neutral: str,
        answer_translated: Optional[str],
        answer_translated_is_fallback: Optional[bool],
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        sid = str(session_id or "").strip()
        rid = str(request_id or "").strip()
        if not rid:
            rid = str(uuid.uuid4())
        if not sid:
            raise ValueError("ConversationHistoryService.on_request_finalized: session_id is required")

        iid = str(identity_id or "").strip() or None
        if iid:
            self._ensure_session_identity_link(session_id=sid, identity_id=iid)

        # If turn wasn't started explicitly, start it now (best-effort).
        if not turn_id:
            turn_id = self._session_store.start_turn(
                session_id=sid,
                request_id=rid,
                identity_id=iid,
                question_neutral="",
                question_translated=None,
                translate_chat=False,
                meta=meta,
            )

        self._session_store.finalize_turn(
            session_id=sid,
            request_id=rid,
            turn_id=str(turn_id),
            answer_neutral=str(answer_neutral or ""),
            answer_translated=answer_translated,
            answer_translated_is_fallback=answer_translated_is_fallback,
            meta=meta,
        )

        if self._durable_store is not None and iid:
            self._durable_store.upsert_turn_final(
                identity_id=iid,
                session_id=sid,
                turn_id=str(turn_id),
                answer_neutral=str(answer_neutral or ""),
                answer_translated=answer_translated,
                answer_translated_is_fallback=answer_translated_is_fallback,
                finalized_at_utc=self._now_utc(),
                meta=meta,
            )

    def get_recent_qa_neutral(self, *, session_id: str, limit: int) -> dict[str, str]:
        sid = str(session_id or "").strip()
        lim = int(limit or 0)
        if lim <= 0:
            lim = 20
        if not sid:
            return {}

        turns = self._session_store.list_recent_finalized_turns(session_id=sid, limit=lim)
        out: dict[str, str] = {}
        for t in turns:
            q = (t.question_neutral or "").strip()
            a = (t.answer_neutral or "").strip() if isinstance(t.answer_neutral, str) else ""
            if not q or not a:
                continue
            out[q] = a
        return out
