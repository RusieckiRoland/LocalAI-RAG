# code_query_engine/pipeline/providers/retrieval_backend_adapter.py
from __future__ import annotations

from typing import Any, Dict, Optional

from .ports import IGraphProvider, IRetrievalBackend
from .retrieval import RetrievalDecision, RetrievalDispatcher
from .retrieval_backend_contract import SearchRequest, SearchResponse, SearchHit


def _extract_id(item: Dict[str, Any]) -> str:
    # Most common keys seen in your pipeline/tests
    for k in ("id", "Id", "ID", "node_id", "chunk_id"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


class RetrievalBackendAdapter(IRetrievalBackend):
    """
    Adapter that exposes the strict backend contract over the existing RetrievalDispatcher + GraphProvider.
    """

    def __init__(
        self,
        *,
        dispatcher: RetrievalDispatcher,
        graph_provider: Optional[IGraphProvider],
        pipeline_settings: Dict[str, Any],
    ) -> None:
        if dispatcher is None:
            raise ValueError("RetrievalBackendAdapter: dispatcher is required")
        self._dispatcher = dispatcher
        self._graph_provider = graph_provider
        self._settings = pipeline_settings or {}

    def search(self, req: SearchRequest) -> SearchResponse:
        decision = RetrievalDecision(mode=req.search_type, query=req.query)

        # Note: dispatcher already accepts filters and top_k.
        results = self._dispatcher.search(
            decision,
            top_k=req.top_k,
            settings=self._settings,
            filters=req.retrieval_filters,
        ) or []

        hits: list[SearchHit] = []
        for i, item in enumerate(results):
            rid = _extract_id(item)
            if not rid:
                continue

            score = 0.0
            for sk in ("score", "Score", "rrf_score"):
                sv = item.get(sk)
                if isinstance(sv, (int, float)):
                    score = float(sv)
                    break

            hits.append(SearchHit(id=rid, score=score, rank=i))

        return SearchResponse(hits=hits)

    def fetch_texts(
        self,
        *,
        node_ids: list[str],
        repository: str,
        branch: str,
        active_index: str | None,
        retrieval_filters: Dict[str, Any],
    ) -> Dict[str, str]:
        if self._graph_provider is None:
            raise ValueError("RetrievalBackendAdapter.fetch_texts: graph_provider is required")

        out = self._graph_provider.fetch_node_texts(
            node_ids=list(node_ids or []),
            repository=repository,
            branch=branch,
            active_index=active_index,
            max_chars=50_000,
        ) or []

        # Contract: mapping id -> text, keep requested order deterministic.
        mapping: Dict[str, str] = {}
        by_id = {str(x.get("id")): str(x.get("text") or "") for x in out if isinstance(x, dict)}
        for nid in node_ids:
            mapping[nid] = by_id.get(nid, "")
        return mapping
