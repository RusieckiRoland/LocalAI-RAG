# File: vector_search/unified_search.py
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import faiss
import numpy as np

from .models import VectorSearchRequest, VectorSearchFilters


def _matches_list(value: Any, allowed: List[str] | None) -> bool:
    """Return True if value is allowed by a simple equality list (scalar equality)."""
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


def _matches_all_tags(value: Any, required_all: List[str] | None) -> bool:
    """Return True if metadata value contains ALL required tags."""
    if not required_all:
        return True
    if value is None:
        return False

    if isinstance(value, (list, tuple, set)):
        have = {str(v) for v in value}
    else:
        have = {str(value)}

    need = {str(v) for v in required_all if str(v).strip()}
    return need.issubset(have)


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
            "permission_tags_all",
            "extra",
        }
        clean = {k: v for k, v in filters.items() if k in allowed}
        f = VectorSearchFilters(**clean)
    else:
        f = VectorSearchFilters()

    # AND across fields (scalar matches)
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

    # --- ACL: require ALL tags ---
    acl_meta = meta.get("permission_tags_all")
    if acl_meta is None:
        acl_meta = meta.get("AclTags") or meta.get("acl_tags") or meta.get("acl_tags_all")

    if not _matches_all_tags(acl_meta, getattr(f, "permission_tags_all", None)):
        return False

    # Extra key/value matches (scalar only)
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


def _unwrap_faiss_index(index: Any) -> Any:
    """
    Best-effort unwrap for wrappers like IndexIDMap.
    """
    cur = index
    for _ in range(3):
        inner = getattr(cur, "index", None)
        if inner is None:
            break
        cur = inner
    return cur


def _get_index_vectors_flat_ip(index: Any) -> np.ndarray:
    """
    Extract raw vectors from an IndexFlat* (CPU) as a (ntotal, d) float32 array.

    This is required for strict prefilter search where we score only allowed ids.
    """
    base = _unwrap_faiss_index(index)

    xb = getattr(base, "xb", None)
    d = getattr(base, "d", None)

    if xb is None or d is None:
        raise TypeError(
            "Strict prefilter search requires a CPU IndexFlat* exposing .xb and .d. "
            f"Got index type: {type(index)} (unwrapped: {type(base)})."
        )

        # In real FAISS IndexFlat*, xb is a FAISS *Vector (C++), so vector_to_array works.
    # In unit tests we may pass xb as a plain numpy array - support that explicitly.
    if isinstance(xb, np.ndarray):
        arr = xb.astype(np.float32, copy=False).reshape(-1)
    else:
        arr = faiss.vector_to_array(xb)

    if arr.size % int(d) != 0:
        raise ValueError(f"IndexFlat xb size mismatch: {arr.size} not divisible by d={d}")

    return arr.reshape(-1, int(d)).astype("float32", copy=False)



def _search_prefiltered_flat_ip(
    *,
    index: Any,
    query_vec: np.ndarray,
    allowed_ids: List[int],
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Strict prefilter vector search for IndexFlatIP:
    - score ONLY the vectors for allowed_ids
    - return top_k results among those
    """
    if not allowed_ids:
        return np.empty((1, 0), dtype=np.float32), np.empty((1, 0), dtype=np.int64)

    vectors = _get_index_vectors_flat_ip(index)  # (ntotal, d)
    sub = vectors[np.array(allowed_ids, dtype=np.int64)]  # (n_allowed, d)

    q = query_vec.reshape(-1)  # (d,)
    scores = sub @ q  # (n_allowed,)

    k = min(int(top_k), int(scores.shape[0]))
    if k <= 0:
        return np.empty((1, 0), dtype=np.float32), np.empty((1, 0), dtype=np.int64)

    # argpartition for top-k, then sort
    idx_part = np.argpartition(scores, -k)[-k:]
    idx_sorted = idx_part[np.argsort(scores[idx_part])[::-1]]

    out_scores = scores[idx_sorted].astype(np.float32, copy=False)
    out_ids = np.array([allowed_ids[int(i)] for i in idx_sorted], dtype=np.int64)

    return out_scores.reshape(1, -1), out_ids.reshape(1, -1)


def search_unified(
    *,
    index,
    metadata: Sequence[Dict[str, Any]],
    embed_model,
    request: VectorSearchRequest,
) -> List[Dict[str, Any]]:
    """
    Perform vector search over unified FAISS index using VectorSearchRequest.

    Order:
      - Default: FAISS search(raw_k) -> filter -> re-rank -> top_k
      - STRICT (ACL only): filter first (ACL) -> score only allowed subset -> top_k

    NOTE:
      Strict prefilter-before-scoring is applied ONLY when ACL tags are present
      (permission_tags_all). Other filters keep the previous contract that relies
      on raw_k oversampling.
    """
    q = (request.text_query or "").strip()
    if not q:
        return []

    # --- Embed query ---
    vec = embed_model.encode([q], convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(vec)

    top_k = int(request.top_k or 5)
    oversample = int(request.oversample_factor or 5)
    raw_k = max(1, top_k * max(1, oversample))

    filt = request.filters or VectorSearchFilters()

    # STRICT mode ONLY for ACL (permission_tags_all)
    if isinstance(filt, VectorSearchFilters):
        strict_acl = bool(getattr(filt, "permission_tags_all", None))
    elif isinstance(filt, dict):
        strict_acl = bool(filt.get("permission_tags_all"))
    else:
        strict_acl = False

    if strict_acl:
        # 1) Prefilter -> allowed ids (ACL + other filters)
        allowed_ids: List[int] = []
        for i, meta in enumerate(metadata):
            if metadata_matches_filters(meta, filt):
                allowed_ids.append(int(i))

        # 2) Score only allowed ids (strict order: filter -> scoring)
        scores, ids = _search_prefiltered_flat_ip(
            index=index,
            query_vec=vec[0],
            allowed_ids=allowed_ids,
            top_k=top_k,
        )
    else:
        # Default: ask FAISS for raw_k, then filter, then top_k
        scores, ids = index.search(vec, raw_k)

    # --- Filter + score ---
    rows: List[Dict[str, Any]] = []

    for raw_score, doc_id in zip(scores[0].tolist(), ids[0].tolist()):
        if doc_id < 0 or doc_id >= len(metadata):
            continue

        meta = metadata[int(doc_id)]

        # Always enforce filters (defensive). In strict_acl mode it should already match.
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

        rows.append(
            {
                "_score": final_score,
                "FaissScore": base_score,
                "Distance": float(1.0 - base_score),
                "File": meta.get("source_file") or meta.get("File"),
                "Id": meta.get("id") or meta.get("Id") or str(doc_id),
                "Content": preview,
                "Metadata": meta,
            }
        )

    # Sort and assign Rank
    rows.sort(key=lambda r: r["_score"], reverse=True)

    out: List[Dict[str, Any]] = []
    for rank, r in enumerate(rows[:top_k], start=1):
        rr = dict(r)
        rr["Rank"] = rank
        rr.pop("_score", None)
        out.append(rr)

    return out


class UnifiedSearch:
    """
    Thin OO wrapper around search_unified(), used by loaders / pipeline.
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
    Adapter to keep legacy call sites working.
    Now also accepts optional `filters` (dict or VectorSearchFilters).
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
                "permission_tags_all",
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
