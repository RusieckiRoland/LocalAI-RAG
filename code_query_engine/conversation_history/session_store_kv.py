from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from typing import Any, Optional

from history.history_backend import HistoryBackend

from .ports import ISessionConversationStore
from .types import ConversationTurn


class KvSessionConversationStore(ISessionConversationStore):
    """
    Redis/mock-backed session store using the existing HistoryBackend (string key/value).

    Storage layout (JSON):
    - key: "conv_hist:<session_id>"
      value: {
        "by_request": { "<request_id>": "<turn_id>", ... },
        "turns": [ {ConversationTurn as dict}, ... ]
      }

    Notes:
    - TTL is best-effort: if the underlying backend supports set(..., ttl=...), we use it.
    - Hard cap is enforced on every write: keep only the last max_turns per session.
    """

    def __init__(self, *, backend: HistoryBackend, ttl_s: Optional[int] = None, max_turns: int = 200) -> None:
        self._backend = backend
        self._ttl_s = ttl_s
        self._max_turns = int(max_turns or 0) if max_turns is not None else 200
        if self._max_turns <= 0:
            self._max_turns = 200

    def _key(self, session_id: str) -> str:
        return f"conv_hist:{session_id}"

    def _now_utc(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _load(self, session_id: str) -> dict[str, Any]:
        raw = self._backend.get(self._key(session_id))
        if not raw:
            return {"by_request": {}, "turns": []}
        try:
            data = json.loads(raw)
        except Exception:
            return {"by_request": {}, "turns": []}
        if not isinstance(data, dict):
            return {"by_request": {}, "turns": []}
        if not isinstance(data.get("by_request"), dict):
            data["by_request"] = {}
        if not isinstance(data.get("turns"), list):
            data["turns"] = []
        return data

    def _save(self, session_id: str, payload: dict[str, Any]) -> None:
        txt = json.dumps(payload, ensure_ascii=False)
        try:
            self._backend.set(self._key(session_id), txt, ttl=self._ttl_s)  # type: ignore[call-arg]
        except TypeError:
            self._backend.set(self._key(session_id), txt)

    def start_turn(
        self,
        *,
        session_id: str,
        request_id: str,
        identity_id: Optional[str],
        question_neutral: str,
        question_translated: Optional[str],
        translate_chat: bool,
        meta: Optional[dict[str, Any]],
    ) -> str:
        session_id = str(session_id or "").strip()
        request_id = str(request_id or "").strip()
        if not session_id:
            raise ValueError("KvSessionConversationStore.start_turn: session_id is required")
        if not request_id:
            raise ValueError("KvSessionConversationStore.start_turn: request_id is required")

        data = self._load(session_id)
        by_request: dict[str, str] = data["by_request"]

        existing = by_request.get(request_id)
        if isinstance(existing, str) and existing.strip():
            return existing

        turn_id = str(uuid.uuid4())
        turn = ConversationTurn(
            turn_id=turn_id,
            session_id=session_id,
            request_id=request_id,
            created_at_utc=self._now_utc(),
            identity_id=identity_id,
            finalized_at_utc=None,
            question_neutral=str(question_neutral or ""),
            answer_neutral=None,
            question_translated=(str(question_translated) if question_translated is not None else None),
            answer_translated=None,
            answer_translated_is_fallback=None,
            metadata=dict(meta or {}),
        )

        by_request[request_id] = turn_id
        data["turns"].append(asdict(turn))
        data["turns"] = data["turns"][-self._max_turns :]
        self._save(session_id, data)
        return turn_id

    def finalize_turn(
        self,
        *,
        session_id: str,
        request_id: str,
        turn_id: str,
        answer_neutral: str,
        answer_translated: Optional[str],
        answer_translated_is_fallback: Optional[bool],
        meta: Optional[dict[str, Any]],
    ) -> None:
        session_id = str(session_id or "").strip()
        request_id = str(request_id or "").strip()
        turn_id = str(turn_id or "").strip()
        if not session_id or not request_id or not turn_id:
            raise ValueError("KvSessionConversationStore.finalize_turn: session_id/request_id/turn_id are required")

        data = self._load(session_id)
        turns: list[dict[str, Any]] = [t for t in data.get("turns", []) if isinstance(t, dict)]
        updated = False
        for t in reversed(turns):
            if str(t.get("turn_id") or "") == turn_id:
                t["finalized_at_utc"] = self._now_utc()
                t["answer_neutral"] = str(answer_neutral or "")
                t["answer_translated"] = str(answer_translated) if answer_translated is not None else None
                t["answer_translated_is_fallback"] = answer_translated_is_fallback
                if meta:
                    old = t.get("metadata")
                    if not isinstance(old, dict):
                        old = {}
                    old.update(dict(meta))
                    t["metadata"] = old
                updated = True
                break

        if not updated:
            raise ValueError("KvSessionConversationStore.finalize_turn: turn_id not found")

        data["turns"] = turns[-self._max_turns :]
        self._save(session_id, data)

    def list_recent_finalized_turns(self, *, session_id: str, limit: int) -> list[ConversationTurn]:
        session_id = str(session_id or "").strip()
        if not session_id:
            return []
        lim = int(limit or 0)
        if lim <= 0:
            lim = 20

        data = self._load(session_id)
        turns_raw = [t for t in data.get("turns", []) if isinstance(t, dict)]

        out: list[ConversationTurn] = []
        for t in turns_raw:
            try:
                finalized_at = t.get("finalized_at_utc")
                if not isinstance(finalized_at, str) or not finalized_at.strip():
                    continue
                ans = t.get("answer_neutral")
                if not isinstance(ans, str) or not ans.strip():
                    continue

                out.append(
                    ConversationTurn(
                        turn_id=str(t.get("turn_id") or ""),
                        session_id=str(t.get("session_id") or session_id),
                        request_id=str(t.get("request_id") or ""),
                        created_at_utc=str(t.get("created_at_utc") or ""),
                        identity_id=(str(t.get("identity_id")) if t.get("identity_id") is not None else None),
                        finalized_at_utc=finalized_at,
                        question_neutral=str(t.get("question_neutral") or ""),
                        answer_neutral=ans,
                        question_translated=(
                            str(t.get("question_translated")) if t.get("question_translated") is not None else None
                        ),
                        answer_translated=(
                            str(t.get("answer_translated")) if t.get("answer_translated") is not None else None
                        ),
                        answer_translated_is_fallback=(
                            bool(t.get("answer_translated_is_fallback"))
                            if t.get("answer_translated_is_fallback") is not None
                            else None
                        ),
                        metadata=(t.get("metadata") if isinstance(t.get("metadata"), dict) else {}),
                    )
                )
            except Exception:
                continue

        # Keep last N finalized turns
        return out[-lim:]
