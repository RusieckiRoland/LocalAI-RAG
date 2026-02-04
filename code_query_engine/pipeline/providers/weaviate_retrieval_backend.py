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
        query_embed_model: Optional[str] = None,
        node_collection: str = "RagNode",
        id_property: str = "canonical_id",
        text_property: str = "text",
        repo_property: str = "repo",
        branch_property: str = "branch",
        snapshot_id_property: str = "snapshot_id",
        permission_tags_property: str = "acl_allow",
        classification_labels_property: str = "classification_labels",
        owner_id_property: str = "owner_id",
        source_system_id_property: str = "source_system_id",
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
        self._classification_prop = classification_labels_property
        self._owner_prop = owner_id_property
        self._source_system_prop = source_system_id_property
        self._query_embed_model = str(query_embed_model or "").strip()
        self._query_embedder: Any = None

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
            res = self._query_bm25(collection=collection, query=q, top_k=top_k, where_filter=where_filter)
        elif search_type in ("semantic", "near_text"):
            qvec = self._encode_query(q)
            res = collection.query.near_vector(
                near_vector=qvec,
                limit=top_k,
                filters=where_filter,
                return_properties=[self._id_prop],
            )
        elif search_type in ("hybrid",):
            qvec = self._encode_query(q)
            alpha = float((request.retrieval_filters or {}).get("hybrid_alpha") or 0.7)
            res = collection.query.hybrid(
                query=q,
                vector=qvec,
                alpha=alpha,
                limit=top_k,
                filters=where_filter,
                return_properties=[self._id_prop],
            )
        else:
            raise ValueError(f"WeaviateRetrievalBackend: unknown search_type={search_type!r}")

        hits = []
        for obj in getattr(res, "objects", []) or []:
            props = getattr(obj, "properties", {}) or {}
            node_id = str(
                props.get(self._id_prop)
                or props.get("canonical_id")
                or props.get("CanonicalId")
                or ""
            ).strip()
            if not node_id:
                continue
            hits.append({"Id": node_id})

        return SearchResponse(hits=hits)

    def _query_bm25(self, *, collection: Any, query: str, top_k: int, where_filter: Any) -> Any:
        return collection.query.bm25(
            query=query,
            limit=top_k,
            filters=where_filter,
            return_properties=[self._id_prop],
        )

    def _get_query_embedder(self) -> Any:
        if self._query_embedder is not None:
            return self._query_embedder
        if not self._query_embed_model:
            raise RuntimeError(
                "WeaviateRetrievalBackend: semantic/hybrid search requires query_embed_model "
                "(e.g. models/embedding/e5-base-v2)."
            )
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as ex:
            raise RuntimeError("WeaviateRetrievalBackend: sentence-transformers is required for query vectorization.") from ex
        py_logger.info("Loading query embedding model for retrieval: %s", self._query_embed_model)
        self._query_embedder = SentenceTransformer(self._query_embed_model)
        return self._query_embedder

    def _encode_query(self, query: str) -> List[float]:
        model = self._get_query_embedder()
        vec = model.encode([query], normalize_embeddings=True)
        try:
            arr = vec[0].astype("float32").tolist()
        except Exception:
            arr = list(vec[0])
        return [float(x) for x in arr]

    def fetch_texts(
        self,
        *,
        node_ids: List[str],
        repository: str,
        snapshot_id: str,
        retrieval_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        Fetch full texts by node ids. Returns dict[node_id] = text.
        """
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
        rf = retrieval_filters or {}
        snapshot_ids_any = rf.get("snapshot_ids_any")
        if isinstance(snapshot_ids_any, list):
            clean = [str(x).strip() for x in snapshot_ids_any if str(x).strip()]
            if clean:
                any_filter = Filter.any_of([Filter.by_property(self._snapshot_id_prop).equal(s) for s in clean])
                f = any_filter if f is None else f & any_filter
            elif snap:
                f = Filter.by_property(self._snapshot_id_prop).equal(snap) if f is None else f & Filter.by_property(self._snapshot_id_prop).equal(snap)
        elif snap:
            f = Filter.by_property(self._snapshot_id_prop).equal(snap) if f is None else f & Filter.by_property(self._snapshot_id_prop).equal(snap)

        # Branch is legacy and not used for scoping (snapshot_id is the only scope).
        _ = branch

        # ACL tags with OR semantics.
        tags = (
            rf.get("acl_tags_any")
            or rf.get("permission_tags_any")
            or rf.get("permission_tags_all")
            or rf.get("acl_tags_all")
        )
        if isinstance(tags, list) and tags:
            f_tags = Filter.by_property(self._perm_prop).contains_any([str(t) for t in tags if str(t).strip()])
            f = f_tags if f is None else f & f_tags

        # Classification labels with ALL/subset semantics.
        labels = rf.get("classification_labels_all")
        if isinstance(labels, list) and labels:
            f_cls = Filter.by_property(self._classification_prop).contains_all(
                [str(t) for t in labels if str(t).strip()]
            )
            f = f_cls if f is None else f & f_cls

        owner_id = str(rf.get("owner_id") or "").strip()
        if owner_id:
            f_owner = Filter.by_property(self._owner_prop).equal(owner_id)
            f = f_owner if f is None else f & f_owner

        source_system_id = str(rf.get("source_system_id") or "").strip()
        if source_system_id:
            f_source = Filter.by_property(self._source_system_prop).equal(source_system_id)
            f = f_source if f is None else f & f_source

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
