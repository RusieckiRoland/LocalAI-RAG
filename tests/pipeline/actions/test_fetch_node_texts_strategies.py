from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchRequest
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchResponse
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchHit
from code_query_engine.pipeline.providers.retrieval import RetrievalDecision
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher


class _GraphProviderStub:
    def __init__(self, *, text_by_id: Dict[str, str], reverse_output: bool) -> None:
        self._text_by_id = dict(text_by_id or {})
        self._reverse_output = bool(reverse_output)

    def fetch_node_texts(
        self,
        *,
        node_ids: List[str],
        repository: str,
        branch: str,
        active_index: Optional[str],
        max_chars: int,
    ) -> List[Dict[str, Any]]:
        out = [{"id": nid, "text": self._text_by_id.get(nid, "")} for nid in list(node_ids or [])]
        if self._reverse_output:
            out.reverse()
        return out


class _TokenCounterStub:
    def __init__(self, *, costs_by_text: Optional[Dict[str, int]] = None) -> None:
        self._costs_by_text = dict(costs_by_text or {})

    def count_tokens(self, s: str) -> int:
        s2 = str(s or "")
        if s2 in self._costs_by_text:
            return int(self._costs_by_text[s2])
        return len(s2.split())


class _DummyDispatcher(RetrievalDispatcher):
    def __init__(self, provider: _GraphProviderStub) -> None:
        self._provider = provider

    def search(
        self,
        decision: RetrievalDecision,
        *,
        top_k: int,
        settings: Dict[str, Any],
        filters: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        # Not used in these tests.
        return []


def _mk_runtime(*, provider: _GraphProviderStub, token_counter: _TokenCounterStub) -> Any:
    dispatcher = _DummyDispatcher(provider)

    backend = RetrievalBackendAdapter(
        dispatcher=dispatcher,
        graph_provider=provider,  # type: ignore[arg-type]
        pipeline_settings={"max_context_tokens": 100},
    )

    return SimpleNamespace(
        graph_provider=provider,
        retrieval_backend=backend,
        token_counter=token_counter,
        pipeline_settings={"max_context_tokens": 100},
    )


def _mk_state(
    *,
    retrieval_seed_nodes: Optional[List[str]] = None,
    graph_expanded_nodes: Optional[List[str]] = None,
    graph_edges: Optional[List[Dict[str, Any]]] = None,
    retrieval_filters: Optional[Dict[str, Any]] = None,
) -> Any:
    return SimpleNamespace(
        repository="repo",
        branch="main",
        retrieval_seed_nodes=list(retrieval_seed_nodes or []),
        graph_expanded_nodes=list(graph_expanded_nodes or []),
        graph_edges=list(graph_edges or []),
        retrieval_filters=dict(retrieval_filters or {}),
        node_nexts=[],
        graph_debug={},
        active_index=None,
    )


def _mk_step(raw: Dict[str, Any]) -> Any:
    return SimpleNamespace(raw=dict(raw or {}))


def _extract_ids(state: Any) -> List[str]:
    # Contract: node_nexts items have "id" (not "node_id").
    return [str(x.get("id")) for x in list(getattr(state, "node_nexts", None) or [])]


def test_fetch_works_without_expand_dependency_tree_uses_retrieval_seed_nodes() -> None:
    """
    Requirement:
    - fetch_node_texts must work even if expand_dependency_tree was NOT executed
    - it must materialize from state.retrieval_seed_nodes
    """
    provider = _GraphProviderStub(
        text_by_id={"A": "A", "B": "B", "C": "C"},
        reverse_output=True,
    )
    runtime = _mk_runtime(provider=provider, token_counter=_TokenCounterStub())
    state = _mk_state(
        retrieval_seed_nodes=["A", "B", "C"],
        graph_expanded_nodes=[],
        graph_edges=[],
        retrieval_filters={"tenant": "t1"},
    )

    step = _mk_step({"prioritization_mode": "seed_first", "budget_tokens": 50})
    action = FetchNodeTextsAction()

    action.do_execute(step, state, runtime)

    assert _extract_ids(state) == ["A", "B", "C"]


def test_seed_first_orders_seeds_then_graph_by_depth_then_id() -> None:
    """
    seed_first:
    1) A,B,C (retrieval order)
    2) then graph nodes by (depth asc, id asc)
    """
    # Graph:
    # A -> D, E
    # D -> F, G
    # B -> H
    edges = [
        {"from_id": "A", "to_id": "D", "edge_type": "calls"},
        {"from_id": "A", "to_id": "E", "edge_type": "calls"},
        {"from_id": "D", "to_id": "F", "edge_type": "calls"},
        {"from_id": "D", "to_id": "G", "edge_type": "calls"},
        {"from_id": "B", "to_id": "H", "edge_type": "calls"},
    ]

    # Intentionally unsorted graph_expanded_nodes
    graph_nodes = ["G", "E", "D", "H", "F"]

    provider = _GraphProviderStub(
        text_by_id={k: k for k in ["A", "B", "C", "D", "E", "F", "G", "H"]},
        reverse_output=True,
    )
    runtime = _mk_runtime(provider=provider, token_counter=_TokenCounterStub())
    state = _mk_state(
        retrieval_seed_nodes=["A", "B", "C"],
        graph_expanded_nodes=graph_nodes,
        graph_edges=edges,
    )

    step = _mk_step({"prioritization_mode": "seed_first", "budget_tokens": 100})
    action = FetchNodeTextsAction()

    action.do_execute(step, state, runtime)

    assert _extract_ids(state) == ["A", "B", "C", "D", "E", "H", "F", "G"]


def test_graph_first_orders_seed_then_its_branch_then_next_seed() -> None:
    """
    graph_first (as requested):
    For each seed in retrieval order:
      - emit the seed
      - emit descendants belonging to this seed branch ordered by (depth asc, id asc)
    """
    # Graph:
    # A -> D, E
    # D -> F, G
    # B -> H, I, J
    # I -> K, L
    # C -> M, N
    edges = [
        {"from_id": "A", "to_id": "D", "edge_type": "calls"},
        {"from_id": "A", "to_id": "E", "edge_type": "calls"},
        {"from_id": "D", "to_id": "F", "edge_type": "calls"},
        {"from_id": "D", "to_id": "G", "edge_type": "calls"},
        {"from_id": "B", "to_id": "H", "edge_type": "calls"},
        {"from_id": "B", "to_id": "I", "edge_type": "calls"},
        {"from_id": "B", "to_id": "J", "edge_type": "calls"},
        {"from_id": "I", "to_id": "K", "edge_type": "calls"},
        {"from_id": "I", "to_id": "L", "edge_type": "calls"},
        {"from_id": "C", "to_id": "M", "edge_type": "calls"},
        {"from_id": "C", "to_id": "N", "edge_type": "calls"},
    ]

    graph_nodes = ["L", "E", "D", "H", "J", "F", "G", "I", "K", "M", "N"]

    provider = _GraphProviderStub(text_by_id={k: k for k in ["A", "B", "C"] + graph_nodes}, reverse_output=True)
    runtime = _mk_runtime(provider=provider, token_counter=_TokenCounterStub())
    state = _mk_state(
        retrieval_seed_nodes=["A", "B", "C"],
        graph_expanded_nodes=graph_nodes,
        graph_edges=edges,
    )

    step = _mk_step({"prioritization_mode": "graph_first", "budget_tokens": 100})
    action = FetchNodeTextsAction()

    action.do_execute(step, state, runtime)

    assert _extract_ids(state) == ["A", "D", "E", "F", "G", "B", "H", "I", "J", "K", "L", "C", "M", "N"]


def test_balanced_interleaves_seed_and_graph_50_50_graph_is_shallow_first() -> None:
    """
    balanced:
    - interleave seed and graph ~50/50 deterministically, starting with seed
    - graph candidates ordered by depth asc, then id asc
    """
    # Graph:
    # A -> D, E
    # B -> H
    # C -> M, N
    edges = [
        {"from_id": "A", "to_id": "D", "edge_type": "calls"},
        {"from_id": "A", "to_id": "E", "edge_type": "calls"},
        {"from_id": "B", "to_id": "H", "edge_type": "calls"},
        {"from_id": "C", "to_id": "M", "edge_type": "calls"},
        {"from_id": "C", "to_id": "N", "edge_type": "calls"},
    ]

    # Graph nodes deliberately scrambled
    graph_nodes = ["N", "E", "D", "M", "H"]

    provider = _GraphProviderStub(text_by_id={k: k for k in ["A", "B", "C"] + graph_nodes}, reverse_output=True)
    runtime = _mk_runtime(provider=provider, token_counter=_TokenCounterStub())
    state = _mk_state(
        retrieval_seed_nodes=["A", "B", "C"],
        graph_expanded_nodes=graph_nodes,
        graph_edges=edges,
    )

    step = _mk_step({"prioritization_mode": "balanced", "budget_tokens": 100})
    action = FetchNodeTextsAction()

    action.do_execute(step, state, runtime)

    assert _extract_ids(state) == ["A", "D", "B", "E", "C", "H", "M", "N"]


def test_atomic_snippets_skip_instead_of_break_for_token_budget() -> None:
    """
    Atomic snippets requirement:
    - if a snippet doesn't fit -> skip it, keep checking next candidates
    """
    provider = _GraphProviderStub(
        text_by_id={
            "A": "tok2",
            "B": "tok5",
            "C": "tok1",
        },
        reverse_output=False,
    )
    token_counter = _TokenCounterStub(costs_by_text={"tok2": 2, "tok5": 5, "tok1": 1})
    runtime = _mk_runtime(provider=provider, token_counter=token_counter)

    state = _mk_state(retrieval_seed_nodes=["A", "B", "C"], graph_expanded_nodes=[], graph_edges=[])

    # budget_tokens=3 should take:
    # A(cost2) -> ok (used=2)
    # B(cost5) -> skip
    # C(cost1) -> ok (used=3)
    step = _mk_step({"prioritization_mode": "seed_first", "budget_tokens": 3})
    action = FetchNodeTextsAction()

    action.do_execute(step, state, runtime)

    assert _extract_ids(state) == ["A", "C"]


def test_max_chars_conflicts_with_budget_tokens_fail_fast() -> None:
    provider = _GraphProviderStub(text_by_id={"A": "A"}, reverse_output=False)
    runtime = _mk_runtime(provider=provider, token_counter=_TokenCounterStub())
    state = _mk_state(retrieval_seed_nodes=["A"])

    step = _mk_step({"max_chars": 10, "budget_tokens": 5, "prioritization_mode": "seed_first"})
    action = FetchNodeTextsAction()

    with pytest.raises(ValueError) as ex:
        action.do_execute(step, state, runtime)

    assert "max_chars cannot be used together with budget_tokens" in str(ex.value)


def test_max_chars_atomic_skip() -> None:
    """
    Atomic snippets for max_chars:
    - if a snippet doesn't fit -> skip it, keep checking next candidates
    """
    provider = _GraphProviderStub(
        text_by_id={
            "A": "12345",  # 5 chars
            "B": "0123456789",  # 10 chars (won't fit if budget is 8)
            "C": "xyz",  # 3 chars
        },
        reverse_output=False,
    )
    runtime = _mk_runtime(provider=provider, token_counter=_TokenCounterStub())
    state = _mk_state(retrieval_seed_nodes=["A", "B", "C"])

    # max_chars=8:
    # A(5) ok -> used=5
    # B(10) skip
    # C(3) ok -> used=8
    step = _mk_step({"max_chars": 8, "prioritization_mode": "seed_first"})
    action = FetchNodeTextsAction()

    action.do_execute(step, state, runtime)

    assert _extract_ids(state) == ["A", "C"]
