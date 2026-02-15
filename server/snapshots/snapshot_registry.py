from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from weaviate.classes.query import Filter
from code_query_engine.weaviate_query_logger import log_weaviate_query


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotInfo:
    # NOTE: This is always snapshot_id (the real identifier).
    id: str
    label: str


@dataclass(frozen=True)
class SnapshotRegistry:
    client: "weaviate.WeaviateClient"
    snapshot_set_collection: str = "SnapshotSet"
    import_collection: str = "ImportRun"

    def resolve_snapshot_id(self, *, snapshot_set_id: str, repository: Optional[str]) -> str:
        snapshots = self.list_snapshots(snapshot_set_id=snapshot_set_id, repository=repository)
        if not snapshots:
            raise ValueError(f"SnapshotSet '{snapshot_set_id}' has no allowed snapshot ids.")
        if len(snapshots) > 1:
            raise ValueError(
                f"SnapshotSet '{snapshot_set_id}' contains {len(snapshots)} snapshots. "
                "Provide 'snapshot_id' explicitly to select one."
            )
        return snapshots[0].id

    def list_snapshots(self, *, snapshot_set_id: str, repository: Optional[str]) -> List[SnapshotInfo]:
        rec = self.fetch_snapshot_set(snapshot_set_id=snapshot_set_id, repository=repository)
        if rec is None:
            raise ValueError(f"Unknown snapshot_set_id '{snapshot_set_id}'.")

        allowed = self._allowed_snapshot_ids(rec)
        if not allowed:
            return []

        repo = str(rec.get("repo") or "").strip() or (repository or "")
        labels = self._resolve_snapshot_labels(rec, repo, allowed)
        return [SnapshotInfo(id=sid, label=labels.get(sid, sid)) for sid in allowed]

    def fetch_snapshot_set(self, *, snapshot_set_id: str, repository: Optional[str]) -> Optional[Dict[str, object]]:
        sid = (snapshot_set_id or "").strip()
        if not sid:
            return None
        coll = self.client.collections.use(self.snapshot_set_collection)
        base = Filter.by_property("snapshot_set_id").equal(sid)
        filters = base
        if repository:
            filters = Filter.all_of([filters, Filter.by_property("repo").equal(repository.strip())])

        t0 = time.time()
        try:
            res = coll.query.fetch_objects(
                filters=filters,
                limit=1,
                # NOTE: allowed_head_shas is informational only; the real IDs are allowed_snapshot_ids.
                return_properties=["snapshot_set_id", "repo", "allowed_snapshot_ids", "allowed_head_shas", "allowed_refs"],
            )
        except Exception as e:
            log_weaviate_query(
                op="snapshot_set_fetch_objects",
                request={
                    "collection": self.snapshot_set_collection,
                    "limit": 1,
                    "filters": filters,
                    "filters_debug": {"snapshot_set_id": sid, "repo": (repository.strip() if repository else None)},
                    "return_properties": ["snapshot_set_id", "repo", "allowed_snapshot_ids", "allowed_head_shas", "allowed_refs"],
                    "repository_hint": repository,
                },
                error=f"{type(e).__name__}: {e}",
                duration_ms=int((time.time() - t0) * 1000),
            )
            raise
        else:
            log_weaviate_query(
                op="snapshot_set_fetch_objects",
                request={
                    "collection": self.snapshot_set_collection,
                    "limit": 1,
                    "filters": filters,
                    "filters_debug": {"snapshot_set_id": sid, "repo": (repository.strip() if repository else None)},
                    "return_properties": ["snapshot_set_id", "repo", "allowed_snapshot_ids", "allowed_head_shas", "allowed_refs"],
                    "repository_hint": repository,
                },
                response=_weaviate_resp_summary(res),
                duration_ms=int((time.time() - t0) * 1000),
            )
        if not res.objects and repository:
            # Fallback: snapshot_set_id is globally unique; do not hard-fail on repo mismatch.
            t1 = time.time()
            try:
                res = coll.query.fetch_objects(
                    filters=base,
                    limit=1,
                    return_properties=["snapshot_set_id", "repo", "allowed_snapshot_ids", "allowed_head_shas", "allowed_refs"],
                )
            except Exception as e:
                log_weaviate_query(
                    op="snapshot_set_fetch_objects_fallback",
                    request={
                        "collection": self.snapshot_set_collection,
                        "limit": 1,
                        "filters": base,
                        "filters_debug": {"snapshot_set_id": sid, "repo": None, "fallback": True},
                        "return_properties": ["snapshot_set_id", "repo", "allowed_snapshot_ids", "allowed_head_shas", "allowed_refs"],
                    },
                    error=f"{type(e).__name__}: {e}",
                    duration_ms=int((time.time() - t1) * 1000),
                )
                raise
            else:
                log_weaviate_query(
                    op="snapshot_set_fetch_objects_fallback",
                    request={
                        "collection": self.snapshot_set_collection,
                        "limit": 1,
                        "filters": base,
                        "filters_debug": {"snapshot_set_id": sid, "repo": None, "fallback": True},
                        "return_properties": ["snapshot_set_id", "repo", "allowed_snapshot_ids", "allowed_head_shas", "allowed_refs"],
                    },
                    response=_weaviate_resp_summary(res),
                    duration_ms=int((time.time() - t1) * 1000),
                )
        if not res.objects:
            return None
        return res.objects[0].properties or {}

    def _allowed_snapshot_ids(self, rec: Dict[str, object]) -> List[str]:
        # IMPORTANT: snapshot_id is the only valid identifier.
        # head_sha is informational and must never be used as an ID or fallback.
        allowed = list(rec.get("allowed_snapshot_ids") or [])
        cleaned = [str(x).strip() for x in allowed if str(x).strip()]
        return self._unique_preserve_order(cleaned)

    def _resolve_snapshot_labels(
        self,
        rec: Dict[str, object],
        repo: str,
        allowed_ids: List[str],
    ) -> Dict[str, str]:
        labels: Dict[str, str] = {}
        allowed_refs = [str(x).strip() for x in (rec.get("allowed_refs") or []) if str(x).strip()]

        if allowed_refs and len(allowed_refs) == len(allowed_ids):
            for sid, ref in zip(allowed_ids, allowed_refs):
                if ref:
                    labels[sid] = ref

        for sid in allowed_ids:
            if sid not in labels:
                labels[sid] = self._resolve_snapshot_label(repo, sid)

        return labels

    def _resolve_snapshot_label(self, repo: str, snapshot_id: str) -> str:
        if not snapshot_id:
            return "unknown"
        try:
            coll = self.client.collections.use(self.import_collection)
            filters = Filter.all_of(
                [
                    Filter.by_property("repo").equal(repo),
                    # IMPORTANT: resolve by snapshot_id only (head_sha is informational).
                    Filter.by_property("snapshot_id").equal(snapshot_id),
                ]
            )
            t0 = time.time()
            res = coll.query.fetch_objects(
                filters=filters,
                limit=5,
                return_properties=[
                    "snapshot_id",
                    "head_sha",
                    "friendly_name",
                    "tag",
                    "ref_name",
                    "branch",
                    "finished_utc",
                    "started_utc",
                ],
            )
            log_weaviate_query(
                op="import_run_fetch_objects",
                request={
                    "collection": self.import_collection,
                    "limit": 5,
                    "filters": repr(filters),
                    "return_properties": [
                        "snapshot_id",
                        "head_sha",
                        "friendly_name",
                        "tag",
                        "ref_name",
                        "branch",
                        "finished_utc",
                        "started_utc",
                    ],
                },
                response=_weaviate_resp_summary(res),
                duration_ms=int((time.time() - t0) * 1000),
            )
        except Exception:
            log_weaviate_query(
                op="import_run_fetch_objects",
                request={
                    "collection": self.import_collection,
                    "limit": 5,
                    "filters": repr(Filter.all_of([Filter.by_property("repo").equal(repo), Filter.by_property("snapshot_id").equal(snapshot_id)])),
                },
                error="Exception (see server logs)",
            )
            LOG.exception("soft-failure: failed to resolve snapshot label for %s", snapshot_id)
            return snapshot_id

        if not res.objects:
            return snapshot_id

        def key(o) -> str:
            p = o.properties or {}
            return str(p.get("finished_utc") or p.get("started_utc") or "")

        best = sorted(res.objects, key=key, reverse=True)[0]
        props = best.properties or {}
        for k in ("friendly_name", "tag", "ref_name", "branch"):
            v = str(props.get(k) or "").strip()
            if v:
                return v
        return snapshot_id

    def _unique_preserve_order(self, items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out


def _weaviate_resp_summary(res: object) -> Dict[str, object]:
    try:
        objs = list(getattr(res, "objects", []) or [])
    except Exception:
        objs = []
    out: Dict[str, object] = {"objects_count": len(objs)}
    if objs:
        try:
            props = getattr(objs[0], "properties", None) or {}
            if isinstance(props, dict):
                out["first_object_keys"] = sorted([str(k) for k in props.keys()])[:50]
        except Exception:
            pass
    return out
