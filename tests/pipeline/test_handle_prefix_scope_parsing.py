import pytest

from code_query_engine.pipeline.actions.prefix_router import PrefixRouterAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class DummyRuntime:
    pass


def _make_step() -> StepDef:
    # Strict contract: every <kind>_prefix must have matching on_<kind>,
    # and on_other must exist (no implicit fallbacks).
    return StepDef(
        id="handle_router_prefix",
        action="prefix_router",
        raw={
            "id": "handle_router_prefix",
            "action": "prefix_router",
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


def _new_state() -> PipelineState:
    return PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )


def test_prefix_router_parses_scope_and_strips_query_for_semantic() -> None:
    step = _make_step()
    state = _new_state()

    # PrefixRouterAction must route only based on state.last_model_response.
    state.last_model_response = "[SEMANTIC:] CS | order creation call chain controller services methods"

    action = PrefixRouterAction()
    nxt = action.execute(step, state, DummyRuntime())

    assert nxt == "next_sem"

    # PrefixRouterAction: routing + prefix stripping only (no retrieval parsing here).
    assert state.last_prefix == "semantic"
    assert state.last_model_response == "CS | order creation call chain controller services methods"

    # Retrieval fields are NOT set by PrefixRouterAction anymore.
    assert state.retrieval_mode == ""
    assert state.retrieval_scope is None
    assert state.retrieval_query == ""
    assert state.retrieval_filters == {}


def test_prefix_router_allows_any_scope_mapping() -> None:
    step = _make_step()
    state = _new_state()
    state.last_model_response = "[SEMANTIC:] ANY | something"

    action = PrefixRouterAction()
    nxt = action.execute(step, state, DummyRuntime())

    assert nxt == "next_sem"
    assert state.last_prefix == "semantic"
    assert state.last_model_response == "ANY | something"

    assert state.retrieval_mode == ""
    assert state.retrieval_scope is None
    assert state.retrieval_query == ""
    assert state.retrieval_filters == {}


def test_prefix_router_invalid_scope_does_not_poison_filters() -> None:
    step = _make_step()
    state = _new_state()
    state.last_model_response = "[SEMANTIC:] NOPE | something that should remain as query"

    action = PrefixRouterAction()
    nxt = action.execute(step, state, DummyRuntime())

    assert nxt == "next_sem"
    assert state.last_prefix == "semantic"
    assert state.last_model_response == "NOPE | something that should remain as query"

    # Still: PrefixRouterAction does not touch retrieval filters.
    assert state.retrieval_filters == {}
