# File: code_query_engine/pipeline/providers/retrieval.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .ports import IRetriever


@dataclass(frozen=True)
class RetrievalDecision:
    mode: str
    query: str


class RetrievalDispatcher:
    """
    Strategy dispatcher for retrieval modes:
      - semantic
      - semantic_rerank
      - bm25
      - hybrid (placeholder)
    """

    def __init__(
        self,
        *,
        semantic: Optional[IRetriever] = None,
        semantic_rerank: Optional[IRetriever] = None,
        bm25: Optional[IRetriever] = None,
    ) -> None:
        self._semantic = semantic
        self._semantic_rerank = semantic_rerank or semantic
        self._bm25 = bm25

    def search(
        self,
        decision: RetrievalDecision,
        *,
        top_k: int,
        settings: Dict[str, Any],
        filters: Optional[Dict[str, List[str]]] = None,
    ) -> List[Dict[str, Any]]:
        mode = (decision.mode or "").strip().lower()
        query = (decision.query or "").strip()
        if not query:
            return []

        bm25_missing_policy = (settings.get("bm25_missing_policy") or "fail_fast").strip().lower()
        hybrid_policy = (settings.get("hybrid_policy") or "not_implemented").strip().lower()

        if mode in ("semantic", ""):
            if self._semantic is None:
                raise RuntimeError("semantic retriever is not configured.")
            return self._semantic.search(query, top_k=top_k, filters=filters)

        if mode == "semantic_rerank":
            if self._semantic_rerank is None:
                raise RuntimeError("semantic_rerank retriever is not configured.")
            return self._semantic_rerank.search(query, top_k=top_k, filters=filters)

        if mode == "bm25":
            if self._bm25 is None:
                if bm25_missing_policy == "fallback_to_semantic":
                    if self._semantic is None:
                        raise RuntimeError("bm25 missing and semantic retriever is not configured.")
                    return self._semantic.search(query, top_k=top_k, filters=filters)
                raise RuntimeError("bm25 retriever is not configured (fail_fast).")
            return self._bm25.search(query, top_k=top_k, filters=filters)

        if mode == "hybrid":
            if hybrid_policy == "fallback_to_semantic":
                if self._semantic is None:
                    raise RuntimeError("hybrid fallback requested but semantic retriever is not configured.")
                return self._semantic.search(query, top_k=top_k, filters=filters)
            raise NotImplementedError("HYBRID mode is planned but not implemented.")

        if mode == "direct":
            return []

        # Unknown mode: deterministic fallback to semantic if possible
        if self._semantic is None:
            raise RuntimeError(f"Unknown retrieval mode '{mode}' and semantic retriever is not configured.")
        return self._semantic.search(query, top_k=top_k, filters=filters)
