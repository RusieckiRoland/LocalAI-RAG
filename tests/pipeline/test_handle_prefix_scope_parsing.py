import pytest

from code_query_engine.pipeline.actions.handle_prefix import HandlePrefixAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class DummyRuntime:
    def __init__(self, last_model_output: str):
        self.last_model_output = last_model_output


def _make_step():
    return StepDef(
        id="handle_router_prefix",
        action="handle_prefix",
        raw={
            "id": "handle_router_prefix",
            "action": "handle_prefix",
            "semantic_prefix": "[SEMANTIC:]",
            "bm25_prefix": "[BM25:]",
            "hybrid_prefix": "[HYBRID:]",
            "semantic_rerank_prefix": "[SEMANTIC_RERANK:]",
            "direct_prefix": "[DIRECT:]",
            "on_semantic": "next_sem",
            "on_bm25": "next_bm25",
            "on_hybrid": "next_hyb",
            "on_semantic_rerank": "next_sr",
            "on_direct": "next_direct",
            "on_other": "next_other",
        },
    )


def test_handle_prefix_parses_scope_and_strips_query_for_semantic():
    step = _make_step()
    runtime = DummyRuntime("[SEMANTIC:] CS | order creation call chain controller services methods")

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    action = HandlePrefixAction()
    nxt = action.execute(step, state, runtime)

    assert nxt == "next_sem"
    assert state.retrieval_mode == "semantic"
    assert state.retrieval_scope == "CS"
    assert state.retrieval_query == "order creation call chain controller services methods"
    assert state.retrieval_filters == {"data_type": ["regular_code"]}


def test_handle_prefix_allows_any_scope_mapping():
    step = _make_step()
    runtime = DummyRuntime("[SEMANTIC:] ANY | checkout confirm create order persist")

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    action = HandlePrefixAction()
    _ = action.execute(step, state, runtime)

    assert state.retrieval_mode == "semantic"
    assert state.retrieval_scope == "ANY"
    assert state.retrieval_query == "checkout confirm create order persist"
    assert state.retrieval_filters == {"data_type": ["regular_code", "db_code"]}


def test_handle_prefix_invalid_scope_does_not_poison_filters():
    step = _make_step()
    runtime = DummyRuntime("[SEMANTIC:] NOPE | something that should remain as query")

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    action = HandlePrefixAction()
    _ = action.execute(step, state, runtime)

    assert state.retrieval_mode == "semantic"
    assert state.retrieval_scope is None
    # For invalid scope token, the whole payload is treated as query (including '|')
    assert state.retrieval_query == "NOPE | something that should remain as query"
    assert state.retrieval_filters == {}
