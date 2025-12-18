# File: vector_search/unified_search.py
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import faiss
import numpy as np

from .models import VectorSearchRequest, VectorSearchFilters


def _matches_list(value: Any, allowed: List[str] | None) -> bool:
    """Return True if value is allowed by a simple equality list."""
    if not allowed:
        return True
    if value is None:
        return False
    s = str(value)
    return any(s == a for a in allowed)


def _matches_prefix(value: Any, prefixes: List[str] | None) -> bool:
    """Return True if value starts with any of the prefixes (case-insensitive)."""
    if not prefixes:
        return True
    if value is None:
        return False
    s = str(value).lower()
    return any(s.startswith(p.lower()) for p in prefixes)


def metadata_matches_filters(meta: Dict[str, Any], filters: Any) -> bool:
    """
    Public helper expected by tests.
    Accepts VectorSearchFilters or a dict-like object.
    """
    if filters is None:
        f = VectorSearchFilters()
    elif isinstance(filters, VectorSearchFilters):
        f = filters
    elif isinstance(filters, dict):
        allowed = {
            "data_type",
            "file_type",
            "kind",
            "project",
            "schema",
            "name_prefix",
            "branch",
            "db_key_in",
            "cs_key_in",
            "extra",
        }
        clean = {k: v for k, v in filters.items() if k in allowed}
        f = VectorSearchFilters(**clean)
    else:
        f = VectorSearchFilters()

    # AND across fields
    if not _matches_list(meta.get("data_type"), f.data_type):
        return False
    if not _matches_list(meta.get("file_type"), f.file_type):
        return False
    if not _matches_list(meta.get("kind"), f.kind):
        return False
    if not _matches_list(meta.get("project"), f.project):
        return False
    if not _matches_list(meta.get("schema"), f.schema):
        return False
    if not _matches_prefix(meta.get("name"), f.name_prefix):
        return False
    if not _matches_list(meta.get("branch"), f.branch):
        return False

    if f.db_key_in and meta.get("db_key") not in set(f.db_key_in):
        return False
    if f.cs_key_in and meta.get("cs_key") not in set(f.cs_key_in):
        return False

    if f.extra:
        for k, allowed in f.extra.items():
            if allowed is None:
                continue
            if isinstance(allowed, list):
                if not _matches_list(meta.get(k), [str(x) for x in allowed]):
                    return False
            else:
                if str(meta.get(k)) != str(allowed):
                    return False

    return True


def search_unified(
    *,
    index,
    metadata: Sequence[Dict[str, Any]],
    embed_model,
    request: VectorSearchRequest,
) -> List[Dict[str, Any]]:
    """
    Perform vector search over unified FAISS index using VectorSearchRequest.

    Args:
        index: FAISS-like object exposing `search(vectors, k)`.
        metadata: sequence of metadata dicts aligned with FAISS rows.
        embed_model: embedding model with `encode(texts, convert_to_numpy=True)`.

    Returns:
        List of result dicts with:
        - Rank
        - FaissScore (raw FAISS score)
        - Distance (1 - similarity, best-effort)
        - File (source_file if available)
        - Id (metadata id or FAISS row index)
        - Content (short preview if available)
        - Metadata (full raw metadata)
    """
    q = (request.text_query or "").strip()
    if not q:
        return []

    # --- Embed query ---
    vec = embed_model.encode([q], convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(vec)

    # --- Raw FAISS search ---
    top_k = int(request.top_k or 5)
    oversample = int(request.oversample_factor or 5)
    raw_k = max(1, top_k * max(1, oversample))

    scores, ids = index.search(vec, raw_k)

    # --- Filter + score ---
    rows: List[Dict[str, Any]] = []
    filt = request.filters or VectorSearchFilters()

    for raw_score, doc_id in zip(scores[0].tolist(), ids[0].tolist()):
        if doc_id < 0 or doc_id >= len(metadata):
            continue

        meta = metadata[int(doc_id)]
        if not metadata_matches_filters(meta, filt):
            continue

        base_score = float(raw_score)
        importance = float(meta.get("importance_score", 1.0) or 1.0)
        final_score = base_score * importance

        # Content preview – accept a few common keys
        text = meta.get("text") or meta.get("Text") or meta.get("Content") or ""
        if request.include_text_preview and isinstance(text, str):
            preview = text[:400]
        else:
            preview = None

        row = {
            "_score": final_score,
            "FaissScore": base_score,
            "Distance": float(1.0 - base_score),
            "File": meta.get("source_file") or meta.get("File"),
            "Id": meta.get("id") or meta.get("Id") or str(doc_id),
            "Content": preview,
            "Metadata": meta,
        }
        rows.append(row)

    # Sort and assign Rank
    rows.sort(key=lambda r: r["_score"], reverse=True)

    out: List[Dict[str, Any]] = []
    for rank, r in enumerate(rows[:top_k], start=1):
        r = dict(r)
        r["Rank"] = rank
        r.pop("_score", None)
        out.append(r)

    return out


class UnifiedSearch:
    """
    Thin OO wrapper around search_unified(), used by loaders / pipeline.

    - index        → FAISS index
    - metadata     → list of metadata dicts
    - embed_model  → embedding model
    """

    def __init__(self, *, index, metadata: Sequence[Dict[str, Any]], embed_model):
        self._index = index
        self._metadata = list(metadata)
        self._embed_model = embed_model

    def search(self, request: VectorSearchRequest) -> List[Dict[str, Any]]:
        return search_unified(
            index=self._index,
            metadata=self._metadata,
            embed_model=self._embed_model,
            request=request,
        )


class UnifiedSearchAdapter:
    """
    Adapter to keep legacy call sites working:
        search(query: str, top_k: int = 5, *, widen=None, alpha=..., beta=...)
    Now also accepts optional `filters` (dict or VectorSearchFilters) for unified index filtering.
    """

    def __init__(self, unified_search: UnifiedSearch):
        self._unified_search = unified_search

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        widen: int | None = None,
        alpha: float = 0.8,
        beta: float = 0.2,
        filters: Any | None = None,
        oversample_factor: int = 5,
        include_text_preview: bool = True,
    ) -> List[Dict[str, Any]]:
        # widen/alpha/beta are ignored (kept for signature compatibility)
        if isinstance(filters, VectorSearchFilters):
            fs = filters
        elif isinstance(filters, dict):
            allowed = {
                "data_type",
                "file_type",
                "kind",
                "project",
                "schema",
                "name_prefix",
                "branch",
                "db_key_in",
                "cs_key_in",
                "extra",
            }
            clean = {k: v for k, v in filters.items() if k in allowed}
            fs = VectorSearchFilters(**clean)
        else:
            fs = VectorSearchFilters()

        req = VectorSearchRequest(
            text_query=query,
            top_k=int(top_k),
            oversample_factor=int(oversample_factor),
            filters=fs,
            include_text_preview=bool(include_text_preview),
        )
        return self._unified_search.search(req)
