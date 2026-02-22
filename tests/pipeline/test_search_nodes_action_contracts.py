from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
import json

import pytest

from code_query_engine.pipeline.actions.search_nodes import SearchNodesAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchHit, SearchResponse
from code_query_engine.pipeline.state import PipelineState


class _BackendStub:
    def __init__(self, hits: Optional[List[SearchHit]] = None, *, client: Any = None) -> None:
        self.hits = list(hits or [])
        self.last_request = None
        self._client = client

    def search(self, request) -> SearchResponse:
        self.last_request = request
        return SearchResponse(hits=list(self.hits))


class _History:
    def add_iteration(self, *_args, **_kwargs) -> None:
        return


def _runtime_with_backend(backend: Any, *, settings: Optional[Dict[str, Any]] = None) -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings=settings or {},
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=_History(),
        logger=None,
        constants=None,
        retrieval_backend=backend,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x, _consultant=None: x,
    )


def _state_with_query(query: str) -> PipelineState:
    state = PipelineState(
        user_query=query,
        session_id="unit",
        consultant="rejewski",
        translate_chat=False,
        repository="Fake",
        snapshot_id="snap",
    )
    state.last_model_response = query
    return state


def test_search_nodes_missing_top_k_fails() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake"})
    state = _state_with_query("token validation")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "semantic"},
    )

    with pytest.raises(ValueError, match="top_k"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_invalid_search_type_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("token validation")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "fuzzy", "top_k": 5},
    )

    with pytest.raises(ValueError, match="invalid search_type"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_empty_query_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(" ")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "semantic", "top_k": 5},
    )

    with pytest.raises(ValueError, match="Empty query"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_rerank_only_semantic() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("token validation")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "bm25", "top_k": 5, "rerank": "keyword_rerank"},
    )

    with pytest.raises(ValueError, match="rerank"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_unknown_rerank_value_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("token validation")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "semantic", "top_k": 5, "rerank": "foo_rerank"},
    )

    with pytest.raises(ValueError, match="invalid rerank"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_codebert_rerank_reserved_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("token validation")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "semantic", "top_k": 5, "rerank": "codebert_rerank"},
    )

    with pytest.raises(ValueError, match="reserved"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_missing_repository_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"top_k": 5})
    state = _state_with_query("token validation")
    state.repository = ""

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "semantic", "top_k": 5},
    )

    with pytest.raises(ValueError, match="repository"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_missing_snapshot_id_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("token validation")
    state.snapshot_id = ""

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={"id": "search", "action": "search_nodes", "search_type": "semantic", "top_k": 5},
    )

    with pytest.raises(ValueError, match="snapshot_id"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_filters_sacred_merge() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"acl_tags_any": ["hr"], "classification_labels_all": ["public"]},
            }
        )
    )
    state.retrieval_filters = {
        "acl_tags_any": ["finance"],
        "classification_labels_all": ["restricted"],
    }

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert "finance" in [str(x) for x in (filters.get("acl_tags_any") or [])]
    assert "restricted" in [str(x) for x in (filters.get("classification_labels_all") or [])]
    assert "hr" not in [str(x) for x in (filters.get("acl_tags_any") or [])]


def test_search_nodes_bm25_match_operator_is_propagated() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "filters": {"data_type": "regular_code"},
                "search_type": "bm25",
                "match_operator": "and",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.bm25_operator == "and"
    assert state.last_search_bm25_operator == "and"


def test_search_nodes_invalid_match_operator_is_ignored() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "filters": {"data_type": "regular_code"},
                "search_type": "bm25",
                "match_operator": "xor",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.bm25_operator is None
    assert state.last_search_bm25_operator is None


def test_search_nodes_bm25_definition_query_keeps_operator_none_when_missing() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "filters": {"data_type": "regular_code"},
                "search_type": "bm25",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.bm25_operator is None
    assert state.last_search_bm25_operator is None


def test_search_nodes_bm25_non_definition_query_keeps_operator_none_when_missing() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "category indexes in catalog",
                "filters": {"data_type": "regular_code"},
                "search_type": "bm25",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.bm25_operator is None
    assert state.last_search_bm25_operator is None


def test_search_nodes_bm25_definition_query_flag_does_not_enable_implicit_and() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "filters": {"data_type": "regular_code"},
                "search_type": "bm25",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
            "default_bm25_and_for_definition_queries": True,
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.bm25_operator is None
    assert state.last_search_bm25_operator is None


def test_search_nodes_allows_top_k_from_payload_when_enabled() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "bm25",
                "top_k": 2,
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "allow_top_k_from_payload": True,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.top_k == 2


def test_search_nodes_auto_search_type_from_payload() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "bm25",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "auto",
            "default_search_type": "hybrid",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.search_type == "bm25"
    assert state.search_type == "bm25"


def test_search_nodes_auto_search_type_from_prefix() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("{\"query\":\"class Category\"}")
    state.last_prefix = "semantic"

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "auto",
            "default_search_type": "hybrid",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.search_type == "semantic"
    assert state.search_type == "semantic"


def test_search_nodes_auto_search_type_without_explicit_source_fails() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "auto",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    with pytest.raises(ValueError, match="requires explicit search_type"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_allow_rrf_k_from_payload() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "hybrid",
                "rrf_k": 9,
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "hybrid",
            "top_k": 5,
            "allow_rrf_k_from_payload": True,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.rrf_k == 9


def test_search_nodes_rerank_widens_top_k() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 4, "rerank_widen_factor": 3})
    state = _state_with_query("{\"query\":\"class Category\"}")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 4,
            "rerank": "keyword_rerank",
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.top_k == 12


def test_search_nodes_ignores_payload_top_k_when_disabled() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "bm25",
                "top_k": 2,
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "allow_top_k_from_payload": False,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.top_k == 5


def test_search_nodes_snapshot_set_rejects_unlisted_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSnapshot:
        def __init__(self, sid: str) -> None:
            self.id = sid

    class _FakeRegistry:
        def __init__(self, _client: Any) -> None:
            return

        def list_snapshots(self, *, snapshot_set_id: str, repository: str) -> List[_FakeSnapshot]:
            assert snapshot_set_id == "set-1"
            assert repository == "Fake"
            return [_FakeSnapshot("allowed-1"), _FakeSnapshot("allowed-2")]

    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.search_nodes.SnapshotRegistry",
        _FakeRegistry,
    )

    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)], client=object())
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5, "snapshot_set_id": "set-1"})
    state = _state_with_query("{\"query\":\"class Category\"}")
    state.snapshot_id = "not-allowed"

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    with pytest.raises(ValueError, match="snapshot_id is not allowed"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_payload_top_k_cannot_exceed_original() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 3})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "bm25",
                "top_k": 10,
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 3,
            "allow_top_k_from_payload": True,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.top_k == 3


def test_search_nodes_allow_rrf_k_from_payload_ignores_non_positive() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "hybrid",
                "rrf_k": 0,
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "hybrid",
            "top_k": 5,
            "allow_rrf_k_from_payload": True,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.rrf_k == 1


def test_search_nodes_snapshot_set_allows_listed_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSnapshot:
        def __init__(self, sid: str) -> None:
            self.id = sid

    class _FakeRegistry:
        def __init__(self, _client: Any) -> None:
            return

        def list_snapshots(self, *, snapshot_set_id: str, repository: str) -> List[_FakeSnapshot]:
            assert snapshot_set_id == "set-1"
            assert repository == "Fake"
            return [_FakeSnapshot("allowed-1"), _FakeSnapshot("allowed-2")]

    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.search_nodes.SnapshotRegistry",
        _FakeRegistry,
    )

    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)], client=object())
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5, "snapshot_set_id": "set-1"})
    state = _state_with_query("{\"query\":\"class Category\"}")
    state.snapshot_id = "allowed-2"

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.snapshot_set_id == "set-1"


def test_search_nodes_clears_retrieval_and_graph_artifacts_but_keeps_context_blocks() -> None:
    backend = _BackendStub(hits=[])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("{\"query\":\"class Category\"}")

    state.retrieval_seed_nodes = ["old"]
    state.retrieval_hits = [{"id": "old"}]
    state.graph_seed_nodes = ["G"]
    state.graph_expanded_nodes = ["G"]
    state.graph_edges = [{"from_id": "A", "to_id": "B"}]
    state.graph_debug = {"reason": "old"}
    state.graph_node_texts = ["x"]
    state.context_blocks = ["ctx"]
    state.node_texts = [{"id": "n1", "text": "old"}]

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert state.retrieval_seed_nodes == []
    assert state.retrieval_hits == []
    assert state.graph_seed_nodes == []
    assert state.graph_expanded_nodes == []
    assert state.graph_edges == []
    assert state.graph_debug == {}
    assert state.graph_node_texts == []
    assert state.context_blocks == ["ctx"]
    assert state.node_texts == []


def test_search_nodes_secondary_snapshot_id_used_in_request() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("{\"query\":\"class Category\"}")
    state.snapshot_id = "primary"
    state.snapshot_id_b = "secondary"

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "snapshot_source": "secondary",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.snapshot_id == "secondary"
    assert backend.last_request.retrieval_filters.get("snapshot_id") == "secondary"


def test_search_nodes_includes_tenant_owner_and_allowed_groups() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(
        backend,
        settings={
            "repository": "Fake",
            "top_k": 5,
            "tenant_id": "t1",
            "owner_id": "o1",
            "allowed_group_ids": ["g1", "g2"],
        },
    )
    state = _state_with_query("{\"query\":\"class Category\"}")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    filters = backend.last_request.retrieval_filters
    assert filters.get("tenant_id") == "t1"
    assert filters.get("owner_id") == "o1"
    assert filters.get("allowed_group_ids") == ["g1", "g2"]


def test_search_nodes_payload_cannot_override_acl_and_labels() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {
                    "acl_tags_any": ["public"],
                    "classification_labels_all": [],
                    "permission_tags_any": ["public"],
                },
            }
        )
    )
    state.retrieval_filters = {
        "acl_tags_any": ["finance"],
        "classification_labels_all": ["restricted"],
    }

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert "finance" in [str(x) for x in (filters.get("acl_tags_any") or [])]
    assert "public" not in [str(x) for x in (filters.get("acl_tags_any") or [])]
    assert "restricted" in [str(x) for x in (filters.get("classification_labels_all") or [])]


def test_search_nodes_payload_cannot_override_access_scope_filters() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(
        backend,
        settings={
            "repository": "Fake",
            "top_k": 5,
            "tenant_id": "tenant-1",
            "owner_id": "owner-1",
            "allowed_group_ids": ["g1", "g2"],
        },
    )
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {
                    "tenant_id": "tenant-evil",
                    "owner_id": "owner-evil",
                    "allowed_group_ids": ["g9"],
                },
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert filters.get("tenant_id") == "tenant-1"
    assert filters.get("owner_id") == "owner-1"
    assert filters.get("allowed_group_ids") == ["g1", "g2"]


def test_search_nodes_payload_cannot_override_repo_or_snapshot_id() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {
                    "repo": "OtherRepo",
                    "snapshot_id": "other-snap",
                },
            }
        )
    )
    state.snapshot_id = "snap"

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert filters.get("repo") == "Fake"
    assert filters.get("snapshot_id") == "snap"


def test_search_nodes_unknown_query_parser_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("{\"query\":\"class Category\"}")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "unknown",
        },
    )

    with pytest.raises(ValueError, match="Unknown query_parser"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_query_parser_alias_resolves() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query("{\"query\":\"class Category\"}")

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "JsonishQueryParser",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.query == "class Category"


def test_search_nodes_invalid_data_type_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "filters": {"data_type": "nonsense"},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    with pytest.raises(ValueError, match="invalid data_type"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_data_type_list_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "filters": {"data_type": ["regular_code"]},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    with pytest.raises(ValueError, match="data_type"):
        SearchNodesAction().execute(step, state, rt)


def test_search_nodes_permission_tags_aliases_normalize_to_acl() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"permission_tags_any": ["hr"]},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert filters.get("acl_tags_any") == ["hr"]


def test_search_nodes_permission_tags_all_alias_normalizes_to_acl() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"permission_tags_all": ["hr"]},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert filters.get("acl_tags_any") == ["hr"]


def test_search_nodes_classification_labels_normalize_string_and_none() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"classification_labels_all": "restricted"},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert filters.get("classification_labels_all") == ["restricted"]

    # Now ensure None removes the key
    state2 = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"classification_labels_all": None},
            }
        )
    )
    SearchNodesAction().execute(step, state2, rt)
    filters2 = dict(state2.retrieval_filters or {})
    assert "classification_labels_all" not in filters2


def test_search_nodes_classification_labels_empty_list_removed() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"classification_labels_all": []},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert "classification_labels_all" not in filters


def test_search_nodes_acl_tags_any_empty_list_removed() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"acl_tags_any": []},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert "acl_tags_any" not in filters


def test_search_nodes_acl_tags_any_string_normalized_to_list() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "token validation",
                "filters": {"acl_tags_any": "hr"},
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    filters = dict(state.retrieval_filters or {})
    assert filters.get("acl_tags_any") == ["hr"]


def test_search_nodes_allow_rrf_k_from_payload_non_hybrid_ignored() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "bm25",
                "rrf_k": 9,
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "allow_rrf_k_from_payload": True,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.rrf_k is None


def test_search_nodes_empty_query_after_parsing_fails() -> None:
    backend = _BackendStub()
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(json.dumps({"query": "  "}))

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "semantic",
            "top_k": 5,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.query == "{\"query\": \"  \"}"


def test_search_nodes_allow_top_k_from_payload_invalid_ignored() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "bm25",
                "top_k": "abc",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "bm25",
            "top_k": 5,
            "allow_top_k_from_payload": True,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.top_k == 5


def test_search_nodes_allow_rrf_k_from_payload_invalid_ignored() -> None:
    backend = _BackendStub(hits=[SearchHit(id="A", score=1.0, rank=1)])
    rt = _runtime_with_backend(backend, settings={"repository": "Fake", "top_k": 5})
    state = _state_with_query(
        json.dumps(
            {
                "query": "class Category",
                "search_type": "hybrid",
                "rrf_k": "abc",
            }
        )
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "id": "search",
            "action": "search_nodes",
            "search_type": "hybrid",
            "top_k": 5,
            "allow_rrf_k_from_payload": True,
            "query_parser": "jsonish_v1",
        },
    )

    SearchNodesAction().execute(step, state, rt)

    assert backend.last_request is not None
    assert backend.last_request.rrf_k is None
