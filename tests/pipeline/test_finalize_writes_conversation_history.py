from code_query_engine.conversation_history.service import ConversationHistoryService
from code_query_engine.conversation_history.session_store_kv import KvSessionConversationStore
from code_query_engine.pipeline.actions.finalize import FinalizeAction
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState
from history.mock_redis import InMemoryMockRedis


def test_finalize_writes_neutral_and_translated_with_fallback() -> None:
    backend = InMemoryMockRedis()
    session_store = KvSessionConversationStore(backend=backend, ttl_s=None, max_turns=50)
    svc = ConversationHistoryService(session_store=session_store, durable_store=None)

    rt = PipelineRuntime(
        pipeline_settings={},
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        conversation_history_service=svc,
        logger=None,
        constants=None,
        retrieval_backend=None,
        graph_provider=None,
        token_counter=None,
    )

    state = PipelineState(
        user_query="Q_PL",
        session_id="s1",
        request_id="r1",
        consultant="c",
        translate_chat=True,
        user_id="u1",
    )
    state.user_question_neutral = "Q_EN"
    state.user_question_translated = "Q_PL"
    state.answer_neutral = "A_EN"
    state.answer_translated = ""  # force fallback

    step = type("S", (), {"raw": {"persist_turn": True}, "id": "finalize", "action": "finalize"})()

    FinalizeAction().do_execute(step, state, rt)

    turns = session_store.list_recent_finalized_turns(session_id="s1", limit=10)
    assert turns
    last = turns[-1]
    assert last.question_neutral == "Q_EN"
    assert last.answer_neutral == "A_EN"
    assert last.answer_translated == "A_EN"
    assert last.answer_translated_is_fallback is True

