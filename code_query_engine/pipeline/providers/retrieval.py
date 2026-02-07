# code_query_engine/pipeline/providers/retrieval.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .ports import IRetriever


@dataclass(frozen=True)
class RetrievalDecision:
    mode: str
    query: str


def _extract_result_id(r: Dict[str, Any]) -> str:
    """
    Best-effort stable ID extraction across different retrievers.

    We prioritize canonical chunk/node IDs if available.
    If missing, we fallback to a composite key based on path+lines (still deterministic).
    """
    nid = r.get("Id") or r.get("id") or r.get("node_id") or r.get("nodeId")
    if nid is not None:
        s = str(nid).strip()
        if s:
            return s

    path = str(r.get("path") or r.get("file") or r.get("File") or "").strip()
    start = r.get("start_line")
    end = r.get("end_line")
    return f"{path}::{start}-{end}"


def _rrf_fuse(
    a: List[Dict[str, Any]],
    b: List[Dict[str, Any]],
    *,
    rrf_k: int,
) -> List[Dict[str, Any]]:
    """
    Reciprocal Rank Fusion (RRF).

    Score(doc) = sum_i 1 / (rrf_k + rank_i)

    - rank starts at 1
    - higher score = better
    - keeps one representative payload per ID (prefers the earliest occurrence from 'a')
    """
    scores: Dict[str, float] = {}
    best_payload: Dict[str, Dict[str, Any]] = {}
    sem_rank: Dict[str, int] = {}
    bm_rank: Dict[str, int] = {}

    def add(results: List[Dict[str, Any]], source_priority: int, rank_map: Dict[str, int]) -> None:
        for idx, r in enumerate(results or [], start=1):
            if not isinstance(r, dict):
                continue
            rid = _extract_result_id(r)
            if not rid:
                continue

            scores[rid] = scores.get(rid, 0.0) + (1.0 / (rrf_k + idx))
            if rid not in rank_map:
                rank_map[rid] = idx

            # Keep deterministic representative payload:
            # prefer the first time we see it; if tie, prefer source 'a' (priority=0).
            if rid not in best_payload:
                best_payload[rid] = r
                best_payload[rid]["_rrf_source_priority"] = source_priority

    add(a, source_priority=0, rank_map=sem_rank)
    add(b, source_priority=1, rank_map=bm_rank)

    fused_ids = sorted(
        scores.keys(),
        key=lambda rid: (
            -scores[rid],
            sem_rank.get(rid, 10**9),
            bm_rank.get(rid, 10**9),
            rid,
        ),
    )

    fused: List[Dict[str, Any]] = []
    for rid in fused_ids:
        item = dict(best_payload[rid])
        item.pop("_rrf_source_priority", None)
        item["rrf_score"] = scores[rid]
        fused.append(item)

    return fused


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

        if mode == "semantic":
            if self._semantic is None:
                return []
            return self._semantic.search(query, top_k=top_k, settings=settings, filters=filters)

        if mode == "hybrid":
            # HybridSearch = Semantic + BM25 fused by RRF.
            # Both sources receive the same enforced filters.
            if self._semantic is None and self._bm25 is None:
                return []

            if self._semantic is None:
                return self._bm25.search(query, top_k=top_k, settings=settings, filters=filters)

            if self._bm25 is None:
                return self._semantic.search(query, top_k=top_k, settings=settings, filters=filters)

            # Optional tuning (strictly optional; defaults are deterministic).
            # - widen factors: allow hybrid to have a richer candidate pool before fusion.
            # - rrf_k controls how quickly rank position decays.
            widen = int(settings.get("hybrid_widen", 2))
            widen = max(1, widen)

            rrf_k = int(settings.get("hybrid_rrf_k", 60))
            rrf_k = max(1, rrf_k)

            sem_k = max(top_k, top_k * widen)
            bm_k = max(top_k, top_k * widen)

            sem_results = self._semantic.search(query, top_k=sem_k, settings=settings, filters=filters) or []
            bm_results = self._bm25.search(query, top_k=bm_k, settings=settings, filters=filters) or []

            fused = _rrf_fuse(sem_results, bm_results, rrf_k=rrf_k)

            # Trim to requested top_k
            return fused[:top_k]

        # Kept for compatibility with existing wiring/tests, even if router no longer emits it.
        if mode == "semantic_rerank":
            if self._semantic_rerank is None:
                return []
            return self._semantic_rerank.search(query, top_k=top_k, settings=settings, filters=filters)

        # Unknown => best-effort semantic
        if self._semantic is None:
            return []
        return self._semantic.search(query, top_k=top_k, settings=settings, filters=filters)
