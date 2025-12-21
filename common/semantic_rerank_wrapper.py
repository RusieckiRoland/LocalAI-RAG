# common/semantic_rerank_wrapper.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class SemanticRerankWrapper:
    """
    A lightweight reranker that wraps an existing semantic retriever.

    It does:
      - wide semantic fetch (top_k -> widen)
      - local keyword scoring on returned text
      - final_score = alpha * (1 - distance) + beta * kw_norm

    Assumptions:
      - base retriever returns dict-like items with some of:
          Distance/distance, Content/content/text/text_preview
      - "distance" is smaller-is-better (typical: Distance = 1 - similarity)
    """

    def __init__(
        self,
        base_searcher: Any,
        *,
        default_widen: Optional[int] = None,
        default_alpha: float = 0.8,
        default_beta: float = 0.2,
    ) -> None:
        self._base = base_searcher
        self._default_widen = default_widen
        self._default_alpha = float(default_alpha)
        self._default_beta = float(default_beta)

    def search(self, query: str, *, top_k: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        widen = int(self._default_widen or max(50, int(top_k) * 10))
        candidates = self._call_base(query=query, top_k=widen, filters=filters) or []
        return self._rerank(
            query=query,
            candidates=candidates,
            top_k=int(top_k),
            alpha=self._default_alpha,
            beta=self._default_beta,
        )

    def _call_base(self, *, query: str, top_k: int, filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Prefer calling with filters, but stay backward-compatible with older searchers.
        try:
            return list(self._base.search(query, top_k=top_k, filters=filters))
        except TypeError:
            return list(self._base.search(query, top_k=top_k))

    @staticmethod
    def _split_camel(s: str) -> str:
        return re.sub(r"([a-z])([A-Z])", r"\1 \2", s or "")

    @staticmethod
    def _get_distance(r: Dict[str, Any]) -> float:
        d = r.get("distance", None)
        if d is None:
            d = r.get("Distance", None)
        try:
            return float(d)
        except Exception:
            return 1.0

    @staticmethod
    def _get_text(r: Dict[str, Any]) -> str:
        # Try common variants across your codebase
        return (
            r.get("content")
            or r.get("Content")
            or r.get("text")
            or r.get("text_preview")
            or ""
        )

    def _rerank(
        self,
        *,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int,
        alpha: float,
        beta: float,
    ) -> List[Dict[str, Any]]:
        toks = [
            t
            for t in re.findall(r"\w+", self._split_camel(query).lower())
            if len(t) >= 3
        ]

        def kw_score(txt: str) -> int:
            if not toks:
                return 0
            low = (txt or "").lower()
            return sum(low.count(t) for t in toks)

        # Score
        max_kw = 1
        for r in candidates:
            dist = self._get_distance(r)
            emb_score = max(0.0, 1.0 - dist)  # smaller distance => higher score
            kw_raw = kw_score(self._get_text(r))

            r["_emb_score"] = emb_score
            r["_kw_raw"] = kw_raw
            if kw_raw > max_kw:
                max_kw = kw_raw

        for r in candidates:
            kw_norm = float(r["_kw_raw"]) / float(max_kw) if max_kw > 0 else 0.0
            r["_final_score"] = float(alpha) * float(r["_emb_score"]) + float(beta) * kw_norm

        # Sort and trim
        candidates.sort(key=lambda x: (-float(x.get("_final_score", 0.0)), self._get_distance(x)))
        out = candidates[:top_k]

        # Cleanup + assign Rank
        for i, r in enumerate(out, start=1):
            r["Rank"] = i
            r.pop("_emb_score", None)
            r.pop("_kw_raw", None)
            r.pop("_final_score", None)

        return out
