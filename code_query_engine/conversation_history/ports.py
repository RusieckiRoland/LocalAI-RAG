from __future__ import annotations

from typing import Any, Optional, Protocol

from .types import ConversationTurn


class ISessionConversationStore(Protocol):
    """
    Session-scoped storage (Redis in prod, mock in tests/dev).
    Keyed by session_id and optimized for fetching last N turns.
    """

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
        """
        Idempotent: for the same (session_id, request_id) must return the same turn_id.
        """
        ...

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
        ...

    def list_recent_finalized_turns(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> list[ConversationTurn]:
        ...


class IUserConversationStore(Protocol):
    """
    Durable user-scoped storage (SQL in prod). Authoritative for authenticated users.
    """

    def upsert_session_link(self, *, identity_id: str, session_id: str) -> None:
        ...

    def insert_turn(self, *, turn: ConversationTurn) -> None:
        ...

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
        ...

    def list_recent_finalized_turns_by_session(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> list[ConversationTurn]:
        ...


class IConversationHistoryService(Protocol):
    """
    Orchestrator: writes to session store for every request, and to durable store when identity_id is present.
    """

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
        ...

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
        ...

    def get_recent_qa_neutral(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> list[tuple[str, str]]:
        """
        Returns recent finalized turns as (question_neutral, answer_neutral) pairs in chronological order (oldest → newest).

        NOTE: This is intentionally a list (not a dict) to preserve duplicates and ordering.
        """
        ...
