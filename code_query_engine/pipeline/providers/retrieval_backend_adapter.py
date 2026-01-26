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

        # Branch is a REQUIRED filter because it maps to a different physical dataset folder.
        if not req.branch:
            raise ValueError("SearchRequest.branch is required (branch maps to a different dataset folder).")

        enforced_filters: Dict[str, Any] = dict(req.retrieval_filters or {})

        # Ensure branch is always applied as a filter (even if caller forgot).
        enforced_filters["branch"] = req.branch

        results = (
            self._dispatcher.search(
                decision,
                top_k=req.top_k,
                settings=self._settings,
                filters=enforced_filters,
            )
            or []
        )

        hits: list[SearchHit] = []
        for i, item in enumerate(results, start=1):  # ✅ 1-based rank
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
        """
        Contract: mapping node_id -> text.

        Note:
        - retrieval_filters are currently not applied inside GraphProvider (graph_provider owns ACL).
        - This adapter keeps deterministic output ordering via the node_ids input list.
        """
        if self._graph_provider is None:
            raise ValueError("RetrievalBackendAdapter.fetch_texts: graph_provider is required")

        out = (
            self._graph_provider.fetch_node_texts(
                node_ids=list(node_ids or []),
                repository=repository,
                branch=branch,
                active_index=active_index,
                max_chars=50_000,
            )
            or []
        )

        by_id: Dict[str, str] = {}
        for x in out:
            if not isinstance(x, dict):
                continue
            rid = str(x.get("id") or "").strip()
            if not rid:
                continue
            by_id[rid] = str(x.get("text") or "")

        # Contract: mapping id -> text, keep requested order deterministic.
        mapping: Dict[str, str] = {}
        for nid in node_ids:
            mapping[nid] = by_id.get(nid, "")
        return mapping
