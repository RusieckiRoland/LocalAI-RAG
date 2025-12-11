# File: vector_search/unified_search.py
from __future__ import annotations

from typing import Any, Dict, List, Sequence

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
    if not isinstance(value, str):
        return False
    low = value.lower()
    return any(low.startswith(p.lower()) for p in prefixes)


def _matches_in_list(value: Any, allowed_list: List[str] | None) -> bool:
    """Return True if value is inside an explicit IN-list."""
    if not allowed_list:
        return True
    if value is None:
        return False
    s = str(value)
    return s in allowed_list


def metadata_matches_filters(meta: Dict[str, Any], filters: VectorSearchFilters) -> bool:
    """
    Check whether a single metadata record satisfies all filters.

    Semantics:
    - Within one field: values are OR-ed.
    - Across fields: AND.
    """
    if filters is None:
        return True

    # Top-level type
    if not _matches_list(meta.get("data_type"), filters.data_type):
        return False

    # Physical / logical file category
    if not _matches_list(meta.get("file_type"), filters.file_type):
        return False

    # SQL kind (Table / Procedure / ...)
    if not _matches_list(meta.get("kind"), filters.kind):
        return False

    # Project / module
    if not _matches_list(meta.get("project"), filters.project):
        return False

    # Schema (dbo, audit, ...)
    if not _matches_list(meta.get("schema"), filters.schema):
        return False

    # Branch name
    if not _matches_list(meta.get("branch"), filters.branch):
        return False

    # name_prefix → simple prefix on logical name
    if not _matches_prefix(meta.get("name"), filters.name_prefix):
        return False

    # db_key_in / cs_key_in → explicit IN lists
    if not _matches_in_list(meta.get("db_key"), filters.db_key_in):
        return False

    if not _matches_in_list(meta.get("cs_key"), filters.cs_key_in):
        return False

    # Extra filters (generic)
    if filters.extra:
        for key, expected in filters.extra.items():
            value = meta.get(key)
            # If expected is a sequence → OR semantics
            if isinstance(expected, (list, tuple, set)):
                if not _matches_list(value, list(expected)):
                    return False
            else:
                if str(value) != str(expected):
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
    emb = embed_model.encode([q], convert_to_numpy=True)
    if not isinstance(emb, np.ndarray):
        emb = np.array(emb, dtype="float32")
    if emb.ndim == 1:
        emb = emb.reshape(1, -1)

    # --- Wide FAISS shot ---
    raw_k = max(request.top_k * request.oversample_factor, request.top_k)
    ntotal = getattr(index, "ntotal", None)
    if ntotal is not None:
        raw_k = min(raw_k, ntotal)
    if raw_k <= 0:
        return []

    distances, indices = index.search(emb, raw_k)

    # --- Collect and filter ---
    rows: List[Dict[str, Any]] = []
    seen_rows: set[int] = set()

    for faiss_idx, raw_score in zip(indices[0], distances[0]):
        if faiss_idx < 0:
            continue
        if faiss_idx in seen_rows:
            continue
        seen_rows.add(int(faiss_idx))

        if faiss_idx >= len(metadata):
            continue

        meta = metadata[faiss_idx] or {}
        # Apply structured filters
        if not metadata_matches_filters(meta, request.filters):
            continue

        # Base FAISS score
        base_score = float(raw_score)
        importance = float(meta.get("importance_score", 1.0) or 1.0)
        final_score = base_score * importance

        # Content preview – we accept a few common keys
        text = (
            meta.get("text")
            or meta.get("Text")
            or meta.get("Content")
            or ""
        )
        if request.include_text_preview and isinstance(text, str):
            preview = text[:400]
        else:
            preview = None

        logical_id = meta.get("id")
        if logical_id is None:
            logical_id = meta.get("Id", int(faiss_idx))

        row: Dict[str, Any] = {
            "_score": final_score,
            "FaissScore": base_score,
            "Rank": 0,  # will be filled after sorting
            "Distance": 1.0 - base_score,
            "File": meta.get("source_file") or meta.get("File"),
            "Id": logical_id,
            "Content": preview or "",
            "Metadata": meta,
        }
        rows.append(row)

    # --- Sort and assign Rank ---
    rows.sort(key=lambda r: r["_score"], reverse=True)

    out: List[Dict[str, Any]] = []
    for rank, r in enumerate(rows[: request.top_k], start=1):
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
        """Delegate to functional search_unified() with stored index/metadata/model."""
        return search_unified(
            index=self._index,
            metadata=self._metadata,
            embed_model=self._embed_model,
            request=request,
        )


class UnifiedSearchAdapter:
    """
    Adapter that makes UnifiedSearch look like the old HybridSearch:

        search(query: str, top_k: int = 5, *, widen=None, alpha=..., beta=...)

    It ignores widen/alpha/beta (we have pure vector semantics),
    but keeps the signature so existing code (dynamic pipeline, helpers)
    can call `.search(...)` unchanged.
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
    ) -> List[Dict[str, Any]]:
        from .models import VectorSearchRequest, VectorSearchFilters

        req = VectorSearchRequest(
            text_query=query,
            top_k=top_k,
            oversample_factor=5,
            filters=VectorSearchFilters(),
            include_text_preview=True,
        )
        return self._unified_search.search(req)
