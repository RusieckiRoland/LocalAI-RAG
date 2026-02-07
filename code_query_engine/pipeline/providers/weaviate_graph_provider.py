from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict, deque
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple
from pathlib import Path

from .ports import IGraphProvider

py_logger = logging.getLogger(__name__)


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        v = (x or "").strip()
        if not v:
            continue
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _normalize_acl_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out = []
        for v in value:
            s = str(v or "").strip()
            if s:
                out.append(s)
        return out
    s = str(value or "").strip()
    return [s] if s else []


def _parse_canonical_id(node_id: str) -> Tuple[str, str]:
    """
    Weaviate canonical id format:
        <repo>::<snapshot_id>::<kind>::<local_id>
    Returns (repo, snapshot_id). Empty strings if parsing fails.
    """
    parts = str(node_id or "").split("::")
    if len(parts) < 4:
        return "", ""
    return parts[0], parts[1]


class WeaviateGraphProvider(IGraphProvider):
    """
    Graph provider backed by Weaviate RagEdge/RagNode collections.

    Responsibilities:
    - Load and cache a unified graph per (repo, snapshot_id).
    - Expand dependency tree using BFS.
    - Filter nodes by ACL tags and classification labels.
    """

    def __init__(
        self,
        *,
        client: Any,
        node_collection: str = "RagNode",
        edge_collection: str = "RagEdge",
        id_property: str = "canonical_id",
        text_property: str = "text",
        edge_from_property: str = "from_canonical_id",
        edge_to_property: str = "to_canonical_id",
        edge_type_property: str = "edge_type",
        repo_property: str = "repo",
        branch_property: str = "branch",
        snapshot_id_property: str = "snapshot_id",
        acl_property: str = "acl_allow",
        classification_property: str = "classification_labels",
        doc_level_property: str = "doc_level",
        classification_labels_universe: Optional[List[str]] = None,
        security_config: Optional[Dict[str, Any]] = None,
        page_size: int = 2000,
    ) -> None:
        if client is None:
            raise ValueError("WeaviateGraphProvider: client is required")

        self._client = client
        self._node_collection = node_collection
        self._edge_collection = edge_collection
        self._id_prop = id_property
        self._text_prop = text_property
        self._edge_from_prop = edge_from_property
        self._edge_to_prop = edge_to_property
        self._edge_type_prop = edge_type_property
        self._repo_prop = repo_property
        self._branch_prop = branch_property
        self._snapshot_id_prop = snapshot_id_property
        self._acl_prop = acl_property
        self._classification_prop = classification_property
        self._doc_level_prop = doc_level_property
        self._classification_universe = (
            _normalize_acl_tags(classification_labels_universe)
            if classification_labels_universe is not None
            else _load_classification_universe_from_config()
        )
        self._security_cfg = _normalize_security_config(security_config)
        self._page_size = int(page_size) if page_size else 2000

        self._adj_cache: Dict[Tuple[str, str], Dict[str, List[Tuple[str, str]]]] = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # IGraphProvider
    # ------------------------------------------------------------------

    def expand_dependency_tree(
        self,
        *,
        seed_nodes: List[str],
        max_depth: int = 2,
        max_nodes: int = 200,
        edge_allowlist: Optional[List[str]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        _ = branch
        _ = filters

        seeds = _dedupe_preserve_order(seed_nodes or [])
        if not seeds:
            return {"nodes": [], "edges": []}

        repo_from_ids, snapshot_id_from_ids = self._resolve_repo_and_snapshot_id(seeds)

        repo = (repository or "").strip()
        if not repo:
            repo = repo_from_ids
        if not repo or repo != repo_from_ids:
            raise ValueError(
                "WeaviateGraphProvider: repository mismatch or missing "
                f"(repository={repository!r} repo_from_ids={repo_from_ids!r})"
            )

        snapshot_id = (snapshot_id or "").strip()
        if snapshot_id and snapshot_id != snapshot_id_from_ids:
            raise ValueError(
                "WeaviateGraphProvider: snapshot_id mismatch "
                f"(snapshot_id={snapshot_id!r} snapshot_id_from_ids={snapshot_id_from_ids!r})"
            )
        if not snapshot_id:
            snapshot_id = snapshot_id_from_ids
        if not snapshot_id:
            raise ValueError("WeaviateGraphProvider: cannot resolve snapshot_id from seed node ids.")

        allow = {str(x).strip().lower() for x in (edge_allowlist or []) if str(x).strip()}
        allow_all = (not allow) or ("*" in allow)

        adj = self._get_adjacency(repo=repo, snapshot_id=snapshot_id)

        visited = set()
        q = deque()
        for s in seeds:
            visited.add(s)
            q.append((s, 0))

        edges_out: List[Dict[str, Any]] = []
        ordered_nodes: List[str] = list(seeds)

        while q and len(visited) < max_nodes:
            node, depth = q.popleft()
            if depth >= max_depth:
                continue

            for rel, to in adj.get(node, []):
                rel_l = (rel or "").strip().lower()
                if not allow_all:
                    rel_key = rel_l
                    if rel_key.startswith("sql_") or rel_key.startswith("cs_"):
                        rel_key = rel_key.split("_", 1)[1]
                    if rel_l not in allow and rel_key not in allow:
                        continue

                edges_out.append({"from": node, "to": to, "type": rel})

                if to in visited:
                    continue

                visited.add(to)
                ordered_nodes.append(to)

                if len(visited) >= max_nodes:
                    break

                q.append((to, depth + 1))

        return {"nodes": ordered_nodes, "edges": edges_out}

    def filter_by_permissions(
        self,
        *,
        node_ids: List[str],
        retrieval_filters: Optional[Dict[str, Any]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        snapshot_id: Optional[str] = None,
    ) -> List[str]:
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception as e:
            raise RuntimeError("WeaviateGraphProvider: cannot import weaviate.classes.query.Filter") from e
        _ = repository
        _ = branch
        _ = snapshot_id

        tags: List[str] = []
        labels: List[str] = []
        rf = retrieval_filters or {}
        if "acl_tags_any" in rf:
            tags = _normalize_acl_tags(rf.get("acl_tags_any"))
        elif "permission_tags_any" in rf:
            tags = _normalize_acl_tags(rf.get("permission_tags_any"))
        elif "permission_tags_all" in rf:
            tags = _normalize_acl_tags(rf.get("permission_tags_all"))
        if "classification_labels_all" in rf:
            labels = _normalize_acl_tags(rf.get("classification_labels_all"))

        if not tags and not labels:
            return list(node_ids or [])

        ids = _dedupe_preserve_order(node_ids or [])
        if not ids:
            return []

        filters = self._build_id_filter(ids)
        acl_filter = self._build_acl_filter(tags)
        classification_filter = self._build_classification_filter(labels)
        clearance_filter = self._build_clearance_filter(rf)
        if acl_filter is not None:
            acl_or_public = Filter.any_of(
                [
                    acl_filter,
                    Filter.by_property(self._acl_prop).is_none(True),
                ]
            )
            filters = filters & acl_or_public
        if classification_filter is not None:
            filters = filters & classification_filter
        if clearance_filter is not None:
            filters = filters & clearance_filter

        coll = self._client.collections.get(self._node_collection)
        res = coll.query.fetch_objects(
            filters=filters,
            limit=len(ids),
            return_properties=[self._id_prop],
        )

        allowed_set = set()
        for obj in res.objects or []:
            props = obj.properties or {}
            cid = str(props.get(self._id_prop) or "").strip()
            if cid:
                allowed_set.add(cid)

        return [i for i in ids if i in allowed_set]

    def fetch_node_texts(
        self,
        *,
        node_ids: List[str],
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        max_chars: int = 50_000,
    ) -> List[Dict[str, Any]]:
        _ = repository
        _ = branch
        _ = snapshot_id

        ids = _dedupe_preserve_order(node_ids or [])
        if not ids:
            return []

        filters = self._build_id_filter(ids)
        coll = self._client.collections.get(self._node_collection)
        res = coll.query.fetch_objects(
            filters=filters,
            limit=len(ids),
            return_properties=[self._id_prop, self._text_prop],
        )

        text_by_id: Dict[str, str] = {}
        for obj in res.objects or []:
            props = obj.properties or {}
            cid = str(props.get(self._id_prop) or "").strip()
            if not cid:
                continue
            text_by_id[cid] = str(props.get(self._text_prop) or "")

        used = 0
        out: List[Dict[str, Any]] = []
        for cid in ids:
            t = text_by_id.get(cid, "")
            if t:
                remaining = max(0, int(max_chars) - used)
                if remaining <= 0:
                    t = ""
                else:
                    if len(t) > remaining:
                        t = t[:remaining]
                    used += len(t)
            out.append({"id": cid, "text": t})
            if used >= max_chars:
                # Continue to keep output order, but remaining texts will be empty.
                continue

        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_repo_and_snapshot_id(self, node_ids: List[str]) -> Tuple[str, str]:
        repo = ""
        snapshot_id = ""
        for nid in node_ids:
            r, h = _parse_canonical_id(nid)
            if not r or not h:
                raise ValueError(f"WeaviateGraphProvider: invalid canonical id '{nid}'.")
            if not repo:
                repo = r
            if not snapshot_id:
                snapshot_id = h
            if r != repo or h != snapshot_id:
                raise ValueError(
                    "WeaviateGraphProvider: seed nodes span multiple snapshots "
                    f"(repo/snapshot_id mismatch: {repo}/{snapshot_id} vs {r}/{h})."
                )
        return repo, snapshot_id

    def _get_adjacency(self, *, repo: str, snapshot_id: str) -> Dict[str, List[Tuple[str, str]]]:
        key = (repo, snapshot_id)
        cached = self._adj_cache.get(key)
        if cached is not None:
            return cached

        with self._cache_lock:
            cached = self._adj_cache.get(key)
            if cached is not None:
                return cached
            adj = self._load_edges(repo=repo, snapshot_id=snapshot_id)
            self._adj_cache[key] = adj
            return adj

    def _load_edges(self, *, repo: str, snapshot_id: str) -> Dict[str, List[Tuple[str, str]]]:
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception as e:
            raise RuntimeError("WeaviateGraphProvider: cannot import weaviate.classes.query.Filter") from e

        filters = Filter.all_of(
            [
                Filter.by_property(self._repo_prop).equal(repo),
                Filter.by_property(self._snapshot_id_prop).equal(snapshot_id),
            ]
        )

        coll = self._client.collections.get(self._edge_collection)
        adj: DefaultDict[str, List[Tuple[str, str]]] = defaultdict(list)

        offset = 0
        while True:
            res = coll.query.fetch_objects(
                filters=filters,
                limit=self._page_size,
                offset=offset,
                return_properties=[self._edge_from_prop, self._edge_to_prop, self._edge_type_prop],
            )

            if not res.objects:
                break

            for obj in res.objects:
                props = obj.properties or {}
                frm = str(props.get(self._edge_from_prop) or "").strip()
                to = str(props.get(self._edge_to_prop) or "").strip()
                rel = str(props.get(self._edge_type_prop) or "edge").strip() or "edge"
                if not frm or not to:
                    continue
                adj[frm].append((rel, to))

            got = len(res.objects)
            offset += got
            if got < self._page_size:
                break

        return dict(adj)


    def _build_id_filter(self, ids: List[str]) -> Any:
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception as e:
            raise RuntimeError("WeaviateGraphProvider: cannot import weaviate.classes.query.Filter") from e

        filters = None
        for cid in ids:
            f = Filter.by_property(self._id_prop).equal(cid)
            filters = f if filters is None else (filters | f)
        if filters is None:
            raise ValueError("WeaviateGraphProvider: empty id filter.")
        return filters

    def _build_acl_filter(self, tags: List[str]) -> Any:
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception as e:
            raise RuntimeError("WeaviateGraphProvider: cannot import weaviate.classes.query.Filter") from e

        cleaned = [str(t).strip() for t in tags if str(t).strip()]
        if not cleaned:
            return None
        return Filter.by_property(self._acl_prop).contains_any(cleaned)

    def _build_classification_filter(self, labels: List[str]) -> Any:
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception as e:
            raise RuntimeError("WeaviateGraphProvider: cannot import weaviate.classes.query.Filter") from e

        sec = self._security_cfg
        if not sec.get("enabled"):
            return None
        if sec.get("kind") != "labels_universe_subset":
            return None

        cleaned = [str(t).strip() for t in labels if str(t).strip()]
        if not cleaned:
            return None

        allow_unlabeled = bool(sec.get("allow_unlabeled", True))
        universe = sec.get("classification_labels_universe") or self._classification_universe
        if universe:
            disallowed = [x for x in universe if x not in cleaned]
            if not disallowed:
                return None
            f_disallowed = Filter.by_property(self._classification_prop).contains_any(disallowed)
            f_not_disallowed = _negate_filter(f_disallowed, Filter)
            if allow_unlabeled:
                f_public_none = Filter.by_property(self._classification_prop).is_none(True)
                return Filter.any_of([f_not_disallowed, f_public_none])
            return f_not_disallowed

        py_logger.warning(
            "WeaviateGraphProvider: classification_labels_universe not configured; "
            "falling back to contains_all (stricter than subset semantics)."
        )
        f_cls = Filter.by_property(self._classification_prop).contains_all(cleaned)
        if allow_unlabeled:
            f_public_none = Filter.by_property(self._classification_prop).is_none(True)
            return Filter.any_of([f_cls, f_public_none])
        return f_cls

    def _build_clearance_filter(self, rf: Dict[str, Any]) -> Any:
        try:
            from weaviate.classes.query import Filter  # type: ignore
        except Exception as e:
            raise RuntimeError("WeaviateGraphProvider: cannot import weaviate.classes.query.Filter") from e

        sec = self._security_cfg
        if not sec.get("enabled"):
            return None
        if sec.get("kind") != "clearance_level":
            return None

        user_level = _normalize_int(rf.get("user_level"))
        if user_level is None:
            user_level = _normalize_int(rf.get("clearance_level"))
        if user_level is None:
            user_level = _normalize_int(rf.get("doc_level_max"))
        if user_level is None:
            py_logger.warning("WeaviateGraphProvider: clearance_level enabled but no user_level in retrieval_filters.")
            return None

        allow_missing = bool(sec.get("allow_missing_doc_level", True))
        f_level = Filter.by_property(self._doc_level_prop).less_or_equal(int(user_level))
        if allow_missing:
            f_none = Filter.by_property(self._doc_level_prop).is_none(True)
            return Filter.any_of([f_level, f_none])
        return f_level


def _load_classification_universe_from_config() -> List[str]:
    env_val = (os.getenv("CLASSIFICATION_LABELS_UNIVERSE") or "").strip()
    if env_val:
        return _normalize_acl_tags([s for s in env_val.split(",")])
    try:
        project_root = Path(__file__).resolve().parents[3]
        cfg_path = project_root / "config.json"
        if not cfg_path.exists():
            return []
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        val = raw.get("classification_labels_universe")
        if isinstance(val, list):
            return _normalize_acl_tags(val)
        if isinstance(val, str):
            return _normalize_acl_tags([s for s in val.split(",")])
    except Exception:
        py_logger.exception("WeaviateGraphProvider: failed to load classification_labels_universe from config.json")
    return []


def _load_security_config_from_config() -> Dict[str, Any]:
    try:
        project_root = Path(__file__).resolve().parents[3]
        cfg_path = project_root / "config.json"
        if not cfg_path.exists():
            return {}
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        return raw.get("permissions") or {}
    except Exception:
        py_logger.exception("WeaviateGraphProvider: failed to load security config from config.json")
        return {}


def _normalize_security_config(security_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if security_config is None:
        security_config = _load_security_config_from_config()
    if not isinstance(security_config, dict):
        return {"enabled": False}

    enabled = bool(security_config.get("security_enabled", False))
    model = security_config.get("security_model") or {}
    kind = str(model.get("kind") or "").strip()
    if kind not in ("labels_universe_subset", "clearance_level"):
        return {"enabled": enabled, "kind": ""}

    if kind == "labels_universe_subset":
        cfg = model.get("labels_universe_subset") or {}
        return {
            "enabled": enabled,
            "kind": kind,
            "allow_unlabeled": bool(cfg.get("allow_unlabeled", True)),
            "classification_labels_universe": _normalize_acl_tags(cfg.get("classification_labels_universe") or []),
        }

    cfg = model.get("clearance_level") or {}
    return {
        "enabled": enabled,
        "kind": kind,
        "allow_missing_doc_level": bool(cfg.get("allow_missing_doc_level", True)),
    }


def _normalize_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None


def _negate_filter(filter_obj: Any, filter_cls: Any) -> Any:
    try:
        return ~filter_obj
    except Exception:
        not_fn = getattr(filter_cls, "not_", None)
        if callable(not_fn):
            return not_fn(filter_obj)
    raise RuntimeError("WeaviateGraphProvider: cannot negate filter; update weaviate-client or filter API")
