import pytest

from code_query_engine.conversation_history.durable_store_memory import InMemoryUserConversationStore
from code_query_engine.conversation_history.service import ConversationHistoryService
from code_query_engine.conversation_history.types import ConversationTurn
from code_query_engine.conversation_history.session_store_kv import KvSessionConversationStore
from history.mock_redis import InMemoryMockRedis


def test_history_falls_back_to_durable_store_when_session_empty() -> None:
    backend = InMemoryMockRedis()
    session_store = KvSessionConversationStore(backend=backend, ttl_s=None, max_turns=200)
    durable = InMemoryUserConversationStore()
    svc = ConversationHistoryService(session_store=session_store, durable_store=durable)

    turn = ConversationTurn(
        turn_id="t1",
        session_id="s1",
        request_id="r1",
        created_at_utc="2026-02-20T20:00:00Z",
        identity_id="u1",
        finalized_at_utc=None,
        question_neutral="Q?",
        answer_neutral=None,
        question_translated=None,
        answer_translated=None,
        answer_translated_is_fallback=None,
        metadata={},
    )
    durable.insert_turn(turn=turn)
    durable.upsert_turn_final(
        identity_id="u1",
        session_id="s1",
        turn_id="t1",
        answer_neutral="A!",
        answer_translated=None,
        answer_translated_is_fallback=None,
        finalized_at_utc="2026-02-20T20:00:01Z",
        meta=None,
    )

    out = svc.get_recent_qa_neutral(session_id="s1", limit=10)
    assert out == [("Q?", "A!")]


def test_durable_store_upsert_missing_turn_raises() -> None:
    durable = InMemoryUserConversationStore()

    with pytest.raises(ValueError, match="turn_id not found"):
        durable.upsert_turn_final(
            identity_id="u1",
            session_id="s1",
            turn_id="missing",
            answer_neutral="A!",
            answer_translated=None,
            answer_translated_is_fallback=None,
            finalized_at_utc="2026-02-20T20:00:01Z",
            meta=None,
        )
