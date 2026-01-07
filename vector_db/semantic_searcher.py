from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from vector_db.unified_index_loader import load_unified_search
from vector_search.models import VectorSearchFilters, VectorSearchRequest
from vector_search.unified_search import UnifiedSearch

py_logger = logging.getLogger(__name__)


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


class SemanticSearcher:
    """
    Semantic retrieval wrapper with the same public contract as Bm25Searcher:

        search(query: str, top_k: int, filters: dict | None, **kwargs) -> list[dict]

    It delegates to UnifiedSearch (FAISS + metadata + embedding model) using VectorSearchRequest.
    """

    def __init__(self, *, unified_search: UnifiedSearch) -> None:
        self._unified = unified_search

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
        return self._unified.search(req)


def load_semantic_search(index_id: Optional[str] = None) -> SemanticSearcher:
    """
    Load the unified semantic search for the active index and wrap it as SemanticSearcher.

    - index_id: optional override; if None, uses config.json active_index_id (via load_unified_search()).
    """
    unified = load_unified_search(index_id)
    return SemanticSearcher(unified_search=unified)
