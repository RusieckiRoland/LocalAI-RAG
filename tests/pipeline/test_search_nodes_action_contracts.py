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
    def __init__(self, hits: Optional[List[SearchHit]] = None) -> None:
        self.hits = list(hits or [])
        self.last_request = None

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
