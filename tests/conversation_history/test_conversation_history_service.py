import pytest

from code_query_engine.conversation_history.durable_store_memory import InMemoryUserConversationStore
from code_query_engine.conversation_history.service import ConversationHistoryService
from code_query_engine.conversation_history.session_store_kv import KvSessionConversationStore
from history.mock_redis import InMemoryMockRedis


def test_conversation_history_service_roundtrip_neutral_qa() -> None:
    backend = InMemoryMockRedis()
    session_store = KvSessionConversationStore(backend=backend, ttl_s=None, max_turns=50)
    durable_store = InMemoryUserConversationStore()
    svc = ConversationHistoryService(session_store=session_store, durable_store=durable_store)

    turn_id = svc.on_request_started(
        session_id="s1",
        request_id="r1",
        identity_id="u1",
        translate_chat=True,
        question_neutral="Q_EN",
        question_translated="Q_PL",
        meta={"k": "v"},
    )

    svc.on_request_finalized(
        session_id="s1",
        request_id="r1",
        identity_id="u1",
        turn_id=turn_id,
        answer_neutral="A_EN",
        answer_translated="A_PL",
        answer_translated_is_fallback=False,
        meta={"m": 1},
    )

    qa = svc.get_recent_qa_neutral(session_id="s1", limit=10)
    assert qa == [("Q_EN", "A_EN")]


def test_session_store_start_turn_is_idempotent() -> None:
    backend = InMemoryMockRedis()
    session_store = KvSessionConversationStore(backend=backend, ttl_s=None, max_turns=50)
    svc = ConversationHistoryService(session_store=session_store, durable_store=None)

    t1 = svc.on_request_started(
        session_id="s1",
        request_id="r1",
        identity_id=None,
        translate_chat=False,
        question_neutral="Q",
        question_translated=None,
    )
    t2 = svc.on_request_started(
        session_id="s1",
        request_id="r1",
        identity_id=None,
        translate_chat=False,
        question_neutral="Q",
        question_translated=None,
    )
    assert t1 == t2


def test_on_request_finalized_without_turn_id_raises() -> None:
    backend = InMemoryMockRedis()
    session_store = KvSessionConversationStore(backend=backend, ttl_s=None, max_turns=50)
    svc = ConversationHistoryService(session_store=session_store, durable_store=None)

    with pytest.raises(ValueError, match="turn_id is required"):
        svc.on_request_finalized(
            session_id="s1",
            request_id="r-finalize-only",
            identity_id=None,
            turn_id=None,
            answer_neutral="A_EN",
            answer_translated=None,
            answer_translated_is_fallback=None,
            meta={"source": "unit"},
        )

    turns = session_store.list_recent_finalized_turns(session_id="s1", limit=10)
    assert len(turns) == 0
    assert svc.get_recent_qa_neutral(session_id="s1", limit=10) == []
