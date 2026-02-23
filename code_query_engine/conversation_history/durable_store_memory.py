from __future__ import annotations

import copy
from typing import Any

from .ports import IUserConversationStore
from .types import ConversationTurn


class InMemoryUserConversationStore(IUserConversationStore):
    """
    Simple in-memory durable store used for dev/tests.
    Persists for the lifetime of the Python process.
    """

    def __init__(self) -> None:
        self._sessions_by_identity: dict[str, set[str]] = {}
        self._turns_by_identity: dict[str, list[ConversationTurn]] = {}

    def upsert_session_link(self, *, identity_id: str, session_id: str) -> None:
        iid = str(identity_id or "").strip()
        sid = str(session_id or "").strip()
        if not iid or not sid:
            return
        self._sessions_by_identity.setdefault(iid, set()).add(sid)

    def insert_turn(self, *, turn: ConversationTurn) -> None:
        if not turn.identity_id:
            return
        iid = str(turn.identity_id or "").strip()
        if not iid:
            return
        self._turns_by_identity.setdefault(iid, []).append(copy.deepcopy(turn))

    def upsert_turn_final(
        self,
        *,
        identity_id: str,
        session_id: str,
        turn_id: str,
        answer_neutral: str,
        answer_translated: str | None,
        answer_translated_is_fallback: bool | None,
        finalized_at_utc: str | None,
        meta: dict[str, Any] | None,
    ) -> None:
        iid = str(identity_id or "").strip()
        if not iid:
            return

        turns = self._turns_by_identity.setdefault(iid, [])
        for i in range(len(turns) - 1, -1, -1):
            t = turns[i]
            if t.turn_id == turn_id and t.session_id == session_id:
                turns[i] = ConversationTurn(
                    **{
                        **t.__dict__,
                        "finalized_at_utc": finalized_at_utc or t.finalized_at_utc,
                        "answer_neutral": str(answer_neutral or ""),
                        "answer_translated": answer_translated,
                        "answer_translated_is_fallback": answer_translated_is_fallback,
                        "metadata": {**(t.metadata or {}), **(meta or {})},
                    }
                )
                return

        # If missing, create a minimal record (best-effort).
        turns.append(
            ConversationTurn(
                turn_id=turn_id,
                session_id=session_id,
                request_id="",
                created_at_utc=finalized_at_utc or "",
                identity_id=iid,
                finalized_at_utc=finalized_at_utc,
                question_neutral="",
                answer_neutral=str(answer_neutral or ""),
                question_translated=None,
                answer_translated=answer_translated,
                answer_translated_is_fallback=answer_translated_is_fallback,
                metadata=dict(meta or {}),
            )
        )

    def list_recent_finalized_turns_by_session(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> list[ConversationTurn]:
        sid = str(session_id or "").strip()
        if not sid:
            return []
        lim = int(limit or 0)
        if lim <= 0:
            lim = 20

        out: list[ConversationTurn] = []
        for turns in self._turns_by_identity.values():
            for t in turns:
                if t.session_id == sid and t.finalized_at_utc:
                    out.append(t)

        out.sort(key=lambda t: t.finalized_at_utc or "")
        return out[-lim:]
