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
    Unifies all retrieval modes behind one call.
    The pipeline computes a RetrievalDecision (mode + query) and optional filters,
    and the dispatcher routes to the correct retriever implementation.
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
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        mode = (decision.mode or "").strip().lower()
        query = (decision.query or "").strip()

        if not query:
            return []

        if mode == "bm25":
            if self._bm25 is None:
                return []
            return self._bm25.search(query, top_k=top_k, settings=settings, filters=filters)

        if mode in ("semantic", "hybrid"):
            # "hybrid" resolved at router-level; here treat as semantic.
            if self._semantic is None:
                return []
            return self._semantic.search(query, top_k=top_k, settings=settings, filters=filters)

        if mode == "semantic_rerank":
            if self._semantic_rerank is None:
                return []
            return self._semantic_rerank.search(query, top_k=top_k, settings=settings, filters=filters)

        # Unknown => best-effort semantic
        if self._semantic is None:
            return []
        return self._semantic.search(query, top_k=top_k, settings=settings, filters=filters)
        