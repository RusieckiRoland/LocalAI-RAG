# code_query_engine/pipeline/providers/retrieval_backend_contract.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional


SearchType = Literal["semantic", "bm25", "hybrid"]
Bm25MatchOperator = Literal["and", "or"]


@dataclass(frozen=True)
class SearchRequest:
    search_type: SearchType
    query: str
    top_k: int
    retrieval_filters: Dict[str, Any]
    repository: str
    snapshot_id: Optional[str] = None
    snapshot_set_id: Optional[str] = None

    # Hybrid-only tuning (YAML: step.raw.rrf_k). Default behavior must be deterministic.
    rrf_k: Optional[int] = None

    # BM25-only tuning: how query tokens are matched (AND/OR semantics).
    bm25_operator: Optional[Bm25MatchOperator] = None


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    rank: int


@dataclass(frozen=True)
class SearchResponse:
    hits: List[SearchHit]
