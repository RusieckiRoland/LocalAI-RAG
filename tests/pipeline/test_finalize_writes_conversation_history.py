from types import SimpleNamespace

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


def test_finalize_uses_neutral_banner_when_translate_chat_disabled() -> None:
    state = PipelineState(
        user_query="Q",
        session_id="s1",
        request_id="r1",
        consultant="c",
        translate_chat=False,
        user_id="u1",
    )
    state.answer_neutral = "A_NEUTRAL"
    state.answer_translated = "A_TRANSLATED"
    state.banner_neutral = "B_NEUTRAL"
    state.banner_translated = "B_TRANSLATED"

    step = type("S", (), {"raw": {"persist_turn": False}, "id": "finalize", "action": "finalize"})()
    runtime = SimpleNamespace(logger=None, conversation_history_service=None)

    FinalizeAction().do_execute(step, state, runtime)

    assert state.final_answer == "B_NEUTRAL\n\nA_NEUTRAL"


def test_finalize_uses_translated_banner_when_translate_chat_enabled() -> None:
    state = PipelineState(
        user_query="Q",
        session_id="s1",
        request_id="r1",
        consultant="c",
        translate_chat=True,
        user_id="u1",
    )
    state.answer_neutral = "A_NEUTRAL"
    state.answer_translated = "A_TRANSLATED"
    state.banner_neutral = "B_NEUTRAL"
    state.banner_translated = "B_TRANSLATED"

    step = type("S", (), {"raw": {"persist_turn": False}, "id": "finalize", "action": "finalize"})()
    runtime = SimpleNamespace(logger=None, conversation_history_service=None)

    FinalizeAction().do_execute(step, state, runtime)

    assert state.final_answer == "B_TRANSLATED\n\nA_TRANSLATED"


def test_finalize_persist_turn_false_skips_logger_and_history_service_calls() -> None:
    class _LoggerSpy:
        def __init__(self) -> None:
            self.called = False

        def log_interaction(self, **_kwargs):
            self.called = True

    class _HistorySpy:
        def __init__(self) -> None:
            self.started = False
            self.finalized = False

        def on_request_started(self, **_kwargs):
            self.started = True
            return "turn-1"

        def on_request_finalized(self, **_kwargs):
            self.finalized = True

    logger = _LoggerSpy()
    svc = _HistorySpy()

    state = PipelineState(
        user_query="Q",
        session_id="s1",
        request_id="r1",
        consultant="c",
        translate_chat=False,
        user_id="u1",
    )
    state.answer_neutral = "A_NEUTRAL"
    step = type("S", (), {"raw": {"persist_turn": False}, "id": "finalize", "action": "finalize"})()
    runtime = SimpleNamespace(logger=logger, conversation_history_service=svc)

    FinalizeAction().do_execute(step, state, runtime)

    assert state.final_answer == "A_NEUTRAL"
    assert logger.called is False
    assert svc.started is False
    assert svc.finalized is False
