from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class FakeGraphProvider:
    def __init__(self, *, node_texts: Optional[List[Dict[str, Any]]] = None) -> None:
        self._node_texts = list(node_texts or [])

    def fetch_node_texts(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return list(self._node_texts)


class _RetrievalBackendStub:
    """Backend stub matching retrieval_contract: node_ids -> text mapping."""

    def __init__(self, graph_provider: Any) -> None:
        self._graph_provider = graph_provider

    def fetch_texts(
        self,
        *,
        node_ids: List[str],
        repository: str,
        snapshot_id: Optional[str],
        retrieval_filters: Dict[str, Any],
    ) -> Dict[str, str]:
        if self._graph_provider is None:
            return {}

        out = self._graph_provider.fetch_node_texts(
            node_ids=list(node_ids or []),
            repository=repository,
            snapshot_id=snapshot_id,
            filters=dict(retrieval_filters or {}),
        ) or []

        by_id = {str(x.get("id")): str(x.get("text") or "") for x in out if isinstance(x, dict)}
        return {nid: by_id[nid] for nid in node_ids if nid in by_id}


class _RetrievalBackendFetchNodesStub:
    def __init__(self, *, nodes: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._nodes = dict(nodes or {})

    def fetch_nodes(
        self,
        *,
        node_ids: List[str],
        repository: str,
        snapshot_id: Optional[str],
        retrieval_filters: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        return {nid: dict(self._nodes.get(nid, {})) for nid in node_ids if nid in self._nodes}


class _TokenCounterStub:
    def __init__(self, per_call: int = 1) -> None:
        self.per_call = per_call

    def count_tokens(self, _text: str) -> int:
        return self.per_call


def test_fetch_node_texts_missing_graph_provider_sets_reason() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        # Use max_chars to avoid requiring runtime.token_counter in this unit test.
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 100},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.graph_expanded_nodes = ["A", "B"]

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=None,
        retrieval_backend=_RetrievalBackendStub(None),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.node_texts == []
    assert state.graph_debug.get("reason") == "ok"
    assert state.graph_debug.get("node_texts_count") == 0


def test_fetch_node_texts_calls_provider_and_stores_result() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={
            "id": "fetch_texts",
            "action": "fetch_node_texts",
        },
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.graph_expanded_nodes = ["A", "B"]

    fake = FakeGraphProvider(node_texts=[{"id": "A", "text": "node A"}, {"id": "B", "text": "node B"}])

    rt = SimpleNamespace(
        pipeline_settings={
            "repository": "nopCommerce",
            "snapshot_id": "snap",
            "max_context_tokens": 4096,
        },
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    # Contract: action returns node_texts with metadata fields.
    assert state.node_texts == [
        {"id": "A", "text": "node A", "is_seed": False, "depth": 1, "parent_id": None},
        {"id": "B", "text": "node B", "is_seed": False, "depth": 1, "parent_id": None},
    ]


def test_fetch_node_texts_budget_tokens_and_max_chars_mutual_exclusive() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens": 10, "max_chars": 50},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.graph_expanded_nodes = ["A"]

    fake = FakeGraphProvider(node_texts=[{"id": "A", "text": "node A"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    with pytest.raises(ValueError, match="max_chars"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_missing_max_context_tokens_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts"},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.graph_expanded_nodes = ["A"]

    fake = FakeGraphProvider(node_texts=[{"id": "A", "text": "node A"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap"},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    with pytest.raises(ValueError, match="max_context_tokens"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_no_nodes_sets_reason() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens": 10},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.graph_expanded_nodes = []
    state.retrieval_seed_nodes = []

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=None,
        retrieval_backend=_RetrievalBackendStub(None),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.node_texts == []
    assert getattr(state, "_fetch_node_texts_debug", {}).get("reason") == "no_nodes_for_fetch_node_texts"


def test_fetch_node_texts_inbox_prioritization_override_applies() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "prioritization_mode": "seed_first", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1", "S2"]
    state.graph_expanded_nodes = ["G1"]
    state.graph_edges = [{"from_id": "S1", "to_id": "G1"}]
    state.inbox = [{"target_step_id": "fetch_texts", "payload": {"prioritization_mode": "balanced"}}]

    fake = FakeGraphProvider(
        node_texts=[
            {"id": "S1", "text": "node S1"},
            {"id": "S2", "text": "node S2"},
            {"id": "G1", "text": "node G1"},
        ]
    )

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.graph_debug.get("prioritization_mode") == "balanced"
    assert state.graph_debug.get("prioritization_mode_source") == "inbox"


def test_fetch_node_texts_inbox_prioritization_invalid_raises() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]
    state.graph_expanded_nodes = ["G1"]
    state.graph_edges = [{"from_id": "S1", "to_id": "G1"}]
    state.inbox = [{"target_step_id": "fetch_texts", "payload": {"prioritization_mode": "not-a-mode"}}]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "node S1"}, {"id": "G1", "text": "node G1"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    with pytest.raises(ValueError, match="invalid prioritization_mode"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_inbox_policy_alias_applies() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "prioritization_mode": "seed_first", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]
    state.graph_expanded_nodes = ["G1"]
    state.graph_edges = [{"from_id": "S1", "to_id": "G1"}]
    state.inbox = [{"target_step_id": "fetch_texts", "payload": {"policy": "balanced"}}]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "node S1"}, {"id": "G1", "text": "node G1"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.graph_debug.get("prioritization_mode") == "balanced"
    assert state.graph_debug.get("prioritization_mode_source") == "inbox"


def test_fetch_node_texts_inbox_prioritization_mode_takes_precedence_over_policy() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "prioritization_mode": "seed_first", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]
    state.graph_expanded_nodes = ["G1"]
    state.graph_edges = [{"from_id": "S1", "to_id": "G1"}]
    state.inbox = [
        {
            "target_step_id": "fetch_texts",
            "payload": {"policy": "balanced", "prioritization_mode": "graph_first"},
        }
    ]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "node S1"}, {"id": "G1", "text": "node G1"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.graph_debug.get("prioritization_mode") == "graph_first"
    assert state.graph_debug.get("prioritization_mode_source") == "inbox"


def test_fetch_node_texts_uses_fetch_nodes_metadata() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]
    state.graph_expanded_nodes = ["G1"]

    backend = _RetrievalBackendFetchNodesStub(
        nodes={
            "S1": {"text": "node S1", "repo_relative_path": "src/a.py", "member_name": "Foo"},
            "G1": {"text": "node G1", "repo_relative_path": "src/b.py", "member_name": "Bar"},
        }
    )

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        retrieval_backend=backend,
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.node_texts == [
        {"id": "S1", "text": "node S1", "repo_relative_path": "src/a.py", "member_name": "Foo", "is_seed": True, "depth": 0, "parent_id": None},
        {"id": "G1", "text": "node G1", "repo_relative_path": "src/b.py", "member_name": "Bar", "is_seed": False, "depth": 1, "parent_id": None},
    ]


def test_fetch_node_texts_budget_tokens_from_settings_applies() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens_from_settings": "fetch_budget"},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1", "S2", "S3"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}, {"id": "S2", "text": "b"}, {"id": "S3", "text": "c"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "fetch_budget": 2, "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert len(state.node_texts) == 2


def test_fetch_node_texts_budget_tokens_from_settings_missing_key_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens_from_settings": "missing"},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="pipeline_settings missing"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_budget_tokens_from_settings_empty_key_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens_from_settings": "  "},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="budget_tokens_from_settings must be a non-empty string"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_missing_token_counter_with_budget_tokens_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens": 5},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=None,
    )

    with pytest.raises(ValueError, match="token_counter is required"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_fetch_nodes_returns_non_dict_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 200},
    )

    class _BadBackend:
        def fetch_nodes(self, **_kwargs: Any) -> Any:
            return ["bad"]

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        retrieval_backend=_BadBackend(),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="fetch_nodes must return Dict"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_fetch_texts_returns_non_dict_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 200},
    )

    class _BadBackend:
        def fetch_texts(self, **_kwargs: Any) -> Any:
            return ["bad"]

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        retrieval_backend=_BadBackend(),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="fetch_texts must return Dict"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_debug_tracks_missing_and_empty_texts() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1", "S2"]

    backend = _RetrievalBackendFetchNodesStub(
        nodes={
            "S1": {"text": ""},  # empty text
            # S2 missing -> missing_texts
        }
    )

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        retrieval_backend=backend,
        token_counter=_TokenCounterStub(per_call=1),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    debug = dict(getattr(state, "_fetch_node_texts_debug", {}) or {})
    backend_debug = dict(debug.get("backend_fetch") or {})
    assert backend_debug.get("missing_texts_count") == 1
    assert backend_debug.get("empty_texts_count") == 1


def test_fetch_node_texts_decision_preview_includes_budget_skips() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens": 1},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1", "S2"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}, {"id": "S2", "text": "b"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    debug = dict(getattr(state, "_fetch_node_texts_debug", {}) or {})
    materialization = dict(debug.get("materialization") or {})
    preview = list(materialization.get("decision_preview") or [])
    assert any(item.get("decision") == "include" for item in preview)
    assert any(item.get("decision") == "skip" and item.get("reason") == "token_budget" for item in preview)


def test_fetch_node_texts_decision_preview_includes_max_chars_skips() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 1},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1", "S2"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}, {"id": "S2", "text": "bb"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    debug = dict(getattr(state, "_fetch_node_texts_debug", {}) or {})
    materialization = dict(debug.get("materialization") or {})
    preview = list(materialization.get("decision_preview") or [])
    assert any(item.get("decision") == "include" for item in preview)
    assert any(item.get("decision") == "skip" and item.get("reason") == "max_chars_budget" for item in preview)


def test_fetch_node_texts_invalid_prioritization_mode_in_yaml_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "prioritization_mode": "nonsense", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="invalid prioritization_mode"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_invalid_max_chars_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 0},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="max_chars must be >= 1"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_invalid_budget_tokens_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens": 0},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="budget_tokens must be >= 1"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_budget_tokens_from_settings_non_positive_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "budget_tokens_from_settings": "fetch_budget"},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "fetch_budget": 0, "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="resolved budget_tokens must be >= 1"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_invalid_max_context_tokens_fails() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts"},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": "nope"},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="max_context_tokens"):
        FetchNodeTextsAction().execute(step, state, rt)


def test_fetch_node_texts_graph_edges_missing_fields_fail() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 200},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["S1"]
    state.graph_expanded_nodes = ["G1"]
    state.graph_edges = [{"from_id": "S1"}]  # missing to_id

    fake = FakeGraphProvider(node_texts=[{"id": "S1", "text": "a"}])

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "snapshot_id": "snap", "max_context_tokens": 4096},
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=_TokenCounterStub(per_call=1),
    )

    with pytest.raises(ValueError, match="graph_edges items must contain from_id/to_id"):
        FetchNodeTextsAction().execute(step, state, rt)
