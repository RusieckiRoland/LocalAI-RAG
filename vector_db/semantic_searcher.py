from __future__ import annotations

import atexit
import logging
import threading
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from vector_search.models import VectorSearchFilters, VectorSearchRequest

py_logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# IMPORTANT:
# - This module MUST NOT import torch/sentence_transformers.
# - Semantic search is executed in a separate worker process to avoid torch/triton reload issues.
# --------------------------------------------------------------------------------------

_semantic_lock = threading.Lock()
_semantic_cache: Dict[str, "SemanticSearcher"] = {}


def _as_list(value: Any) -> Optional[List[str]]:
    """Normalize filter values to list[str] or None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        out = [str(v).strip() for v in value if str(v).strip()]
        return out or None
    s = str(value).strip()
    return [s] if s else None


def _build_vector_filters(filters: Any | None) -> VectorSearchFilters:
    """
    Convert the pipeline-style filters dict into VectorSearchFilters.

    Notes:
    - Vector search supports only a known set of fields + `extra` for arbitrary metadata keys.
    - The pipeline often uses "repository", but unified metadata typically stores it as "repo".
      We map repository -> extra["repo"] and also accept repo/repo_name.
    """
    if filters is None:
        return VectorSearchFilters()

    # Already a VectorSearchFilters instance.
    if isinstance(filters, VectorSearchFilters):
        return filters

    if not isinstance(filters, dict):
        return VectorSearchFilters()

    # Known fields (list equality, except name_prefix = prefix match).
    data_type = _as_list(filters.get("data_type"))
    file_type = _as_list(filters.get("file_type"))
    kind = _as_list(filters.get("kind"))
    project = _as_list(filters.get("project"))
    schema = _as_list(filters.get("schema"))
    name_prefix = _as_list(filters.get("name_prefix"))
    branch = _as_list(filters.get("branch"))
    db_key_in = _as_list(filters.get("db_key_in"))
    cs_key_in = _as_list(filters.get("cs_key_in"))

    # Extra fields: free-form metadata constraints.
    extra: Dict[str, Any] = {}
    extra_in = filters.get("extra")
    if isinstance(extra_in, dict):
        extra.update(extra_in)

    # Repository mapping (pipeline uses "repository"; metadata uses "repo"/"repo_name").
    repo_vals = _as_list(filters.get("repository")) or _as_list(filters.get("repo")) or _as_list(filters.get("repo_name"))
    if repo_vals:
        extra.setdefault("repo", repo_vals)
        extra.setdefault("repo_name", repo_vals)

    return VectorSearchFilters(
        data_type=data_type,
        file_type=file_type,
        kind=kind,
        project=project,
        schema=schema,
        name_prefix=name_prefix,
        branch=branch,
        db_key_in=db_key_in,
        cs_key_in=cs_key_in,
        extra=extra,
    )


def _filters_to_dict(fs: VectorSearchFilters) -> Dict[str, Any]:
    """
    Serialize VectorSearchFilters to a plain dict (worker-safe).
    Supports dataclass / pydantic style objects.
    """
    if hasattr(fs, "model_dump"):
        return dict(fs.model_dump())
    if is_dataclass(fs):
        return asdict(fs)
    # Best-effort fallback
    out: Dict[str, Any] = {}
    for k in ("data_type", "file_type", "kind", "project", "schema", "name_prefix", "branch", "db_key_in", "cs_key_in", "extra"):
        out[k] = getattr(fs, k, None)
    return out


def _request_to_dict(req: VectorSearchRequest) -> Dict[str, Any]:
    """
    Serialize VectorSearchRequest to a plain dict (worker-safe).
    """
    if hasattr(req, "model_dump"):
        d = dict(req.model_dump())
        # Ensure nested filters is serializable
        fs = d.get("filters")
        if isinstance(fs, VectorSearchFilters):
            d["filters"] = _filters_to_dict(fs)
        return d

    if is_dataclass(req):
        d = asdict(req)
        # Ensure nested filters is serializable
        fs = d.get("filters")
        if isinstance(fs, VectorSearchFilters):
            d["filters"] = _filters_to_dict(fs)
        return d

    # Best-effort fallback
    return {
        "text_query": getattr(req, "text_query", ""),
        "top_k": getattr(req, "top_k", 10),
        "oversample_factor": getattr(req, "oversample_factor", 5),
        "filters": _filters_to_dict(getattr(req, "filters", VectorSearchFilters())),
        "include_text_preview": bool(getattr(req, "include_text_preview", True)),
    }


class SemanticSearcher:
    """
    Semantic retrieval wrapper with the same public contract as Bm25Searcher:

        search(query: str, top_k: int, filters: dict | None, **kwargs) -> list[dict]

    It delegates to a separate worker process to avoid in-process torch/triton re-init issues.
    """

    def __init__(self, *, index_id: Optional[str]) -> None:
        self._index_id = (index_id or "").strip() or "__active__"

        # Lazy init worker client
        from vector_db.semantic_worker import SemanticWorkerClient  # local import by design

        self._client = SemanticWorkerClient(index_id=index_id)

    def search(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        oversample = int(kwargs.get("oversample_factor") or 5)
        include_text_preview = bool(kwargs.get("include_text_preview", True))

        fs = _build_vector_filters(filters)

        req = VectorSearchRequest(
            text_query=q,
            top_k=max(int(top_k or 1), 1),
            oversample_factor=max(int(oversample or 1), 1),
            filters=fs,
            include_text_preview=include_text_preview,
        )

        payload = _request_to_dict(req)
        return self._client.search(payload)


def load_semantic_search(index_id: Optional[str] = None) -> SemanticSearcher:
    """
    Load semantic search wrapper.

    Thread-safety:
    - Safe for concurrent calls (multi-user server).
    - Cached per index_id to avoid creating multiple worker clients for the same index.
    """
    key = (index_id or "").strip() or "__active__"

    cached = _semantic_cache.get(key)
    if cached is not None:
        return cached

    with _semantic_lock:
        cached = _semantic_cache.get(key)
        if cached is not None:
            return cached

        searcher = SemanticSearcher(index_id=index_id)
        _semantic_cache[key] = searcher

        # Ensure worker processes are terminated on interpreter exit.
        try:
            from vector_db.semantic_worker import shutdown_all_workers  # local import by design
            atexit.register(shutdown_all_workers)
        except Exception:
            # atexit is best-effort; never break runtime
            pass

        return searcher
