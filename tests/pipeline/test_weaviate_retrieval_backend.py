from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchRequest
from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend


class _FakeQuery:
    def __init__(self) -> None:
        self.bm25_calls: List[Dict[str, Any]] = []
        self.hybrid_calls: List[Dict[str, Any]] = []
        self.near_vector_calls: List[Dict[str, Any]] = []
        self.fetch_objects_calls: List[Dict[str, Any]] = []
        self.bm25_objects: List[Any] = []
        self.hybrid_objects: List[Any] = []
        self.fetch_objects_objects: List[Any] = []
        self.raise_on_query_props = False

    def bm25(self, **kwargs: Any) -> Any:
        self.bm25_calls.append(dict(kwargs))
        if self.raise_on_query_props and kwargs.get("query_properties") is not None:
            raise RuntimeError("bm25 boom")
        return SimpleNamespace(objects=list(self.bm25_objects))

    def hybrid(self, **kwargs: Any) -> Any:
        self.hybrid_calls.append(dict(kwargs))
        return SimpleNamespace(objects=list(self.hybrid_objects))

    def near_vector(self, **kwargs: Any) -> Any:
        self.near_vector_calls.append(dict(kwargs))
        return SimpleNamespace(objects=[])

    def fetch_objects(self, **kwargs: Any) -> Any:
        self.fetch_objects_calls.append(dict(kwargs))
        return SimpleNamespace(objects=list(self.fetch_objects_objects))


class _FakeCollection:
    def __init__(self, query: _FakeQuery) -> None:
        self.query = query
        self.tenant: Optional[str] = None

    def with_tenant(self, snapshot_id: str) -> "_FakeCollection":
        self.tenant = snapshot_id
        return self


class _FakeCollections:
    def __init__(self, collection: _FakeCollection) -> None:
        self._collection = collection
        self.last_get: Optional[str] = None

    def get(self, name: str) -> _FakeCollection:
        self.last_get = name
        return self._collection


class _FakeClient:
    def __init__(self, collection: _FakeCollection) -> None:
        self.collections = _FakeCollections(collection)


def _install_bm25_factory(monkeypatch) -> None:
    weaviate_mod = types.ModuleType("weaviate")
    weaviate_classes_mod = types.ModuleType("weaviate.classes")
    weaviate_query_mod = types.ModuleType("weaviate.classes.query")

    class _Filter:
        @staticmethod
        def by_property(_name: str) -> "_Filter":
            return _Filter()

        def equal(self, _value: Any) -> "_Filter":
            return self

        @staticmethod
        def all_of(_filters: List[Any]) -> "_Filter":
            return _Filter()

    weaviate_query_mod.Filter = _Filter

    grpc_mod = types.ModuleType("weaviate.collections.classes.grpc")

    class _BM25OperatorFactory:
        @staticmethod
        def and_() -> str:
            return "OP_AND"

        @staticmethod
        def or_(minimum_match: int = 1) -> Dict[str, Any]:
            return {"op": "or", "min": minimum_match}

    grpc_mod.BM25OperatorFactory = _BM25OperatorFactory

    monkeypatch.setitem(sys.modules, "weaviate", weaviate_mod)
    monkeypatch.setitem(sys.modules, "weaviate.classes", weaviate_classes_mod)
    monkeypatch.setitem(sys.modules, "weaviate.classes.query", weaviate_query_mod)
    monkeypatch.setitem(sys.modules, "weaviate.collections", types.ModuleType("weaviate.collections"))
    monkeypatch.setitem(sys.modules, "weaviate.collections.classes", types.ModuleType("weaviate.collections.classes"))
    monkeypatch.setitem(sys.modules, "weaviate.collections.classes.grpc", grpc_mod)


def test_weaviate_bm25_operator_is_passed(monkeypatch) -> None:
    _install_bm25_factory(monkeypatch)
    query = _FakeQuery()
    query.bm25_objects = [SimpleNamespace(properties={"canonical_id": "X"})]
    collection = _FakeCollection(query)
    client = _FakeClient(collection)
    backend = WeaviateRetrievalBackend(
        client=client,
        query_embed_model="models/embedding/e5-base-v2",
        security_config={"security_enabled": True, "acl_enabled": True},
    )

    req = SearchRequest(
        search_type="bm25",
        query="alpha beta",
        top_k=3,
        retrieval_filters={},
        repository="Repo",
        snapshot_id="snap",
        bm25_operator="and",
    )

    res = backend.search(req)
    assert res.hits and res.hits[0].id == "X"
    assert query.bm25_calls
    assert query.bm25_calls[0]["operator"] == "OP_AND"


def test_weaviate_bm25_does_not_fallback_to_hybrid(monkeypatch) -> None:
    _install_bm25_factory(monkeypatch)
    query = _FakeQuery()
    query.bm25_objects = []
    query.hybrid_objects = [SimpleNamespace(properties={"canonical_id": "Y"})]
    collection = _FakeCollection(query)
    client = _FakeClient(collection)
    backend = WeaviateRetrievalBackend(
        client=client,
        query_embed_model="models/embedding/e5-base-v2",
        security_config={"security_enabled": True, "acl_enabled": True},
    )
    backend._encode_query = lambda _q: [0.1, 0.2]  # type: ignore[assignment]

    req = SearchRequest(
        search_type="bm25",
        query="alpha beta",
        top_k=3,
        retrieval_filters={},
        repository="Repo",
        snapshot_id="snap",
        bm25_operator="or",
    )

    res = backend.search(req)
    assert res.hits == []
    assert len(query.hybrid_calls) == 0


def test_weaviate_bm25_does_not_retry_without_query_properties(monkeypatch) -> None:
    _install_bm25_factory(monkeypatch)
    query = _FakeQuery()
    query.raise_on_query_props = True
    query.bm25_objects = [SimpleNamespace(properties={"canonical_id": "Z"})]
    collection = _FakeCollection(query)
    client = _FakeClient(collection)
    backend = WeaviateRetrievalBackend(
        client=client,
        query_embed_model="models/embedding/e5-base-v2",
        security_config={"security_enabled": True, "acl_enabled": True},
    )

    req = SearchRequest(
        search_type="bm25",
        query="alpha beta",
        top_k=3,
        retrieval_filters={},
        repository="Repo",
        snapshot_id="snap",
        bm25_operator="and",
    )

    with pytest.raises(RuntimeError, match="bm25 boom"):
        backend.search(req)
    assert len(query.bm25_calls) == 1
    assert query.bm25_calls[0]["query_properties"] is not None


def test_weaviate_ignores_bm25_operator_for_non_bm25(monkeypatch) -> None:
    _install_bm25_factory(monkeypatch)
    query = _FakeQuery()
    collection = _FakeCollection(query)
    client = _FakeClient(collection)
    backend = WeaviateRetrievalBackend(
        client=client,
        query_embed_model="models/embedding/e5-base-v2",
        security_config={"security_enabled": True, "acl_enabled": True},
    )
    backend._encode_query = lambda _q: [0.1, 0.2]  # type: ignore[assignment]

    req = SearchRequest(
        search_type="semantic",
        query="alpha beta",
        top_k=3,
        retrieval_filters={},
        repository="Repo",
        snapshot_id="snap",
        bm25_operator="and",
    )

    res = backend.search(req)
    assert res.hits == []
    assert len(query.near_vector_calls) == 1
    assert query.bm25_calls == []


def test_weaviate_bm25_operator_factory_missing_raises(monkeypatch) -> None:
    _install_bm25_factory(monkeypatch)
    monkeypatch.delitem(sys.modules, "weaviate.collections.classes.grpc", raising=False)

    query = _FakeQuery()
    query.bm25_objects = [SimpleNamespace(properties={"canonical_id": "X"})]
    collection = _FakeCollection(query)
    client = _FakeClient(collection)
    backend = WeaviateRetrievalBackend(
        client=client,
        query_embed_model="models/embedding/e5-base-v2",
        security_config={"security_enabled": True, "acl_enabled": True},
    )

    req = SearchRequest(
        search_type="bm25",
        query="alpha beta",
        top_k=3,
        retrieval_filters={},
        repository="Repo",
        snapshot_id="snap",
        bm25_operator="and",
    )

    with pytest.raises(RuntimeError, match="BM25OperatorFactory is unavailable"):
        backend.search(req)


def test_weaviate_fetch_nodes_maps_security_fields(monkeypatch) -> None:
    query = _FakeQuery()
    query.fetch_objects_objects = [
        SimpleNamespace(
            properties={
                "canonical_id": "N1",
                "text": "class Category {}",
                "repo_relative_path": "src/Category.cs",
                "source_file": "Category.cs",
                "project_name": "Nop.Core",
                "class_name": "Category",
                "member_name": "Category",
                "symbol_type": "TypeRollup",
                "signature": "Nop.Core.Domain.Catalog.Category#TYPE_ROLLUP",
                "data_type": "regular_code",
                "file_type": "cs",
                "domain": "code",
                "acl_allow": ["dev", "ops"],
                "classification_labels": ["internal", "restricted"],
                "doc_level": 4,
            }
        )
    ]
    collection = _FakeCollection(query)
    client = _FakeClient(collection)
    backend = WeaviateRetrievalBackend(
        client=client,
        query_embed_model="models/embedding/e5-base-v2",
        security_config={"security_enabled": True, "acl_enabled": True},
    )

    monkeypatch.setattr(backend, "_build_in_filter", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backend, "_build_where_filter", lambda **_kwargs: None)

    out = backend.fetch_nodes(
        node_ids=["N1"],
        repository="Repo",
        snapshot_id="snap",
        retrieval_filters={},
    )

    assert "N1" in out
    row = out["N1"]
    assert row["text"] == "class Category {}"
    assert row["repo_relative_path"] == "src/Category.cs"
    assert row["acl_allow"] == ["dev", "ops"]
    assert row["classification_labels"] == ["internal", "restricted"]
    assert row["doc_level"] == 4

    assert query.fetch_objects_calls
    props = list(query.fetch_objects_calls[0].get("return_properties") or [])
    assert "acl_allow" in props
    assert "classification_labels" in props
    assert "doc_level" in props
