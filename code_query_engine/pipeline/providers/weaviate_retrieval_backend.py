from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from code_query_engine.pipeline.providers.ports import IRetrievalBackend
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchRequest, SearchResponse

py_logger = logging.getLogger(__name__)


class WeaviateRetrievalBackend(IRetrievalBackend):
    """
    IRetrievalBackend implementation backed by Weaviate.

    IMPORTANT:
    - This class does NOT build the Weaviate client.
    - Connection/auth/readiness MUST be handled by vector_db/weaviate_client.py (single source of truth).
    """

    def __init__(
        self,
        *,
        client: Any,
        node_collection: str = "RagNode",
        id_property: str = "canonical_id",
        text_property: str = "text",
        repo_property: str = "repo",
        branch_property: str = "branch",
        snapshot_id_property: str = "snapshot_id",
        permission_tags_property: str = "acl_allow",
    ) -> None:
        if client is None:
            raise ValueError("WeaviateRetrievalBackend: client is required")

        self._client = client
        self._node_collection = node_collection
        self._id_prop = id_property
        self._text_prop = text_property
        self._repo_prop = repo_property
        self._branch_prop = branch_property
        self._snapshot_id_prop = snapshot_id_property
        self._perm_prop = permission_tags_property

    # ---------------------------------------------------------------------
    # IRetrievalBackend
    # ---------------------------------------------------------------------

    def search(self, request: SearchRequest) -> SearchResponse:
        """
        Returns SearchResponse where response.hits is a list of dicts.
        Each dict MUST contain at least {"Id": "<node_id>"} (adapter expects this).
        """
        q = (request.query or "").strip()
        if not q:
            return SearchResponse(hits=[])

        collection = self._client.collections.get(self._node_collection)

        # Minimal filters (repo/branch). More advanced ACL/filter composition can be added next.
        snapshot_id = (request.snapshot_id or "").strip()
        if not snapshot_id:
            snapshot_id = str((request.retrieval_filters or {}).get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise ValueError("WeaviateRetrievalBackend: snapshot_id is required.")

        where_filter = self._build_where_filter(
            repository=request.repository,
            snapshot_id=snapshot_id,
            branch=None,
            retrieval_filters=request.retrieval_filters,
        )

        search_type = (request.search_type or "").strip().lower()
        top_k = max(int(request.top_k or 1), 1)

        # NOTE:
        # We deliberately keep this "fail-fast" if client API differs.
        # If your weaviate-client differs, we adjust against your installed version.
        if search_type in ("bm25", "keyword"):
            res = collection.query.bm25(
                query=q,
                limit=top_k,
                filters=where_filter,
                return_properties=[self._id_prop],
            )
        elif search_type in ("semantic", "near_text"):
            res = collection.query.near_text(
                query=q,
                limit=top_k,
                filters=where_filter,
                return_properties=[self._id_prop],
            )
        elif search_type in ("hybrid",):
            # If you want alpha configured, pass it via request.retrieval_filters or pipeline settings later.
            res = collection.query.hybrid(
                query=q,
                limit=top_k,
                filters=where_filter,
                return_properties=[self._id_prop],
            )
        else:
            raise ValueError(f"WeaviateRetrievalBackend: unknown search_type={search_type!r}")

        hits = []
        for obj in getattr(res, "objects", []) or []:
            props = getattr(obj, "properties", {}) or {}
            node_id = (props.get(self._id_prop) or "").strip()
            if not node_id:
                continue
            hits.append({"Id": node_id})

        return SearchResponse(hits=hits)

    def fetch_texts(
        self,
        *,
        node_ids: List[str],
        repository: str,
        snapshot_id: str,
        retrieval_filters: Optional[Dict[str, Any]] = None,
        active_index: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Fetch full texts by node ids. Returns dict[node_id] = text.
        """
        _ = active_index
        if not node_ids:
            return {}

        collection = self._client.collections.get(self._node_collection)

        # We fetch objects and map by canonical_id (id_property).
        # This assumes canonical_id is stored as a property (not UUID).
        where_filter = self._build_in_filter(self._id_prop, node_ids)

        scope_filter = self._build_where_filter(
            repository=repository,
            snapshot_id=snapshot_id,
            branch=None,
            retrieval_filters=retrieval_filters or {},
        )

        if scope_filter is not None:
            where_filter = where_filter & scope_filter

        res = collection.query.fetch_objects(
            limit=len(node_ids),
            filters=where_filter,
            return_properties=[self._id_prop, self._text_prop],
        )

        out: Dict[str, str] = {}
        for obj in getattr(res, "objects", []) or []:
            props = getattr(obj, "properties", {}) or {}
            node_id = (props.get(self._id_prop) or "").strip()
            text = str(props.get(self._text_prop) or "")
            if node_id:
                out[node_id] = text

        return out

    # ---------------------------------------------------------------------
    # Filter helpers (minimal, safe defaults)
    # ---------------------------------------------------------------------

    def _build_where_filter(
        self,
        *,
        repository: Optional[str],
        snapshot_id: Optional[str],
        branch: Optional[str],
        retrieval_filters: Optional[Dict[str, Any]],
    ) -> Any:
        """
        Minimal filter composition. Uses weaviate.classes.query.Filter if available.
        """
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception:
            # Fail-fast: we expect v4 style API since weaviate_client uses connect_to_local().
            raise RuntimeError("WeaviateRetrievalBackend: cannot import weaviate.classes.query.Filter; check weaviate-client version")

        f = None

        repo = (repository or "").strip()
        if repo:
            f = Filter.by_property(self._repo_prop).equal(repo) if f is None else f & Filter.by_property(self._repo_prop).equal(repo)

        snap = (snapshot_id or "").strip()
        if snap:
            f = Filter.by_property(self._snapshot_id_prop).equal(snap) if f is None else f & Filter.by_property(self._snapshot_id_prop).equal(snap)

        # Branch is legacy and not used for scoping (snapshot_id is the only scope).
        _ = branch

        # ACL hook (optional): expect list under retrieval_filters["permission_tags_all"] etc.
        rf = retrieval_filters or {}
        tags = rf.get("permission_tags_all") or rf.get("acl_tags_all")
        if isinstance(tags, list) and tags:
            # This requires the property to be a string[] field in Weaviate schema.
            f_tags = Filter.by_property(self._perm_prop).contains_all([str(t) for t in tags if str(t).strip()])
            f = f_tags if f is None else f & f_tags

        return f

    def _build_in_filter(self, prop: str, values: List[str]) -> Any:
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception:
            raise RuntimeError("WeaviateRetrievalBackend: cannot import weaviate.classes.query.Filter; check weaviate-client version")

        cleaned = [str(v).strip() for v in values if str(v).strip()]
        if not cleaned:
            raise ValueError("WeaviateRetrievalBackend: empty id list for IN filter")

        return Filter.by_property(prop).contains_any(cleaned)
