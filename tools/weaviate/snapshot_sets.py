#!/usr/bin/env python3
from __future__ import annotations

"""
SnapshotSet management CLI for LocalAI-RAG / Weaviate.

What is a SnapshotSet?
- A named allowlist of repo snapshots that can be queried (e.g., two tags/branches).
- This is NOT a Weaviate vector index. It is a logical selector that later becomes a
  filter on RagNode/RagEdge by snapshot_id.

Design notes:
- SnapshotSet stores both human-friendly refs (branches/tags) and immutable snapshot_id values.
- Refs can move over time in Git; snapshot_id is the source of truth for query filters.
- We resolve refs -> snapshot_id using ImportRun entries (created by the importer).

Collections used:
- ImportRun (already created by importer)
- SnapshotSet (created by this tool)

Examples:
  # List all SnapshotSets
  python -m tools.weaviate.snapshot_sets --env list

  # Show one SnapshotSet
  python -m tools.weaviate.snapshot_sets --env show --id nopCommerce_4-60_4-90

  # Create SnapshotSet from refs (resolved to snapshot_id via ImportRun)
  python -m tools.weaviate.snapshot_sets --env add \
    --id nopCommerce_4-60_4-90 \
    --repo nopCommerce \
    --refs release-4.60.0 release-4.90.0 \
    --description "Public browsing: nopCommerce 4.60 + 4.90"

  # Create SnapshotSet from explicit snapshot_id allowlist (no resolver)
  python -m tools.weaviate.snapshot_sets --env add \
    --id nopCommerce_custom \
    --repo nopCommerce \
    --snapshot-ids dcfb... 1234...

  # Delete
  python -m tools.weaviate.snapshot_sets --env delete --id nopCommerce_4-60_4-90

  # Discover imported snapshots (ImportRun) and create SnapshotSet interactively
  python -m tools.weaviate.snapshot_sets --env snapshots --repo nopCommerce

  # Discover snapshots across all repos, select by numbers non-interactively
  python -m tools.weaviate.snapshot_sets --env snapshots --select 1,2 --id my_set_name
"""

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import weaviate
import weaviate.classes as wvc
from weaviate.classes.query import Filter
from weaviate.util import generate_uuid5

# Ensure imports work both as:
#   python tools/weaviate/snapshot_sets.py ...
# and:
#   python -m tools.weaviate.snapshot_sets ...
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vector_db.weaviate_client import create_client, get_settings, load_dotenv  # noqa: E402

LOG = logging.getLogger("snapshot_sets")

COL_IMPORT = "ImportRun"
COL_SET = "SnapshotSet"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitize_id_part(s: str) -> str:
    """
    Make a SnapshotSet id safe-ish and readable.
    Keep [a-zA-Z0-9_-], replace everything else with '-'.
    """
    s = (s or "").strip()
    s = re.sub(r"[^a-zA-Z0-9_\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _choose_ref_label(p: Dict[str, Any]) -> str:
    """
    Pick a human-friendly label for an ImportRun row.
    Prefer: tag, ref_name, branch.
    """
    for k in ("tag", "ref_name", "branch"):
        v = str(p.get(k) or "").strip()
        if v:
            return v
    return "unknown-ref"


def connect_weaviate(host: str, http_port: int, grpc_port: int, api_key: str = "") -> "weaviate.WeaviateClient":
    overrides = {
        "host": host.strip() if host else "",
        "http_port": int(http_port) if http_port else 0,
        "grpc_port": int(grpc_port) if grpc_port else 0,
        "api_key": api_key.strip() if api_key else "",
    }
    settings = get_settings(overrides={k: v for k, v in overrides.items() if v})
    return create_client(settings)


def ensure_schema(client: "weaviate.WeaviateClient") -> None:
    existing = set(client.collections.list_all(simple=True))

    # SnapshotSet is metadata-only; we still use self_provided() for simplicity.
    if COL_SET not in existing:
        client.collections.create(
            name=COL_SET,
            vector_config=wvc.config.Configure.Vectors.self_provided(),
            properties=[
                wvc.config.Property(name="snapshot_set_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="repo", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="allowed_refs", data_type=wvc.config.DataType.TEXT_ARRAY),
                wvc.config.Property(name="allowed_snapshot_ids", data_type=wvc.config.DataType.TEXT_ARRAY),
                # Legacy compatibility (pre-snapshot_id)
                wvc.config.Property(name="allowed_head_shas", data_type=wvc.config.DataType.TEXT_ARRAY),
                wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="created_utc", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="updated_utc", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="is_active", data_type=wvc.config.DataType.BOOL),
            ],
        )
        LOG.info("Created collection: %s", COL_SET)


@dataclass(frozen=True)
class SnapshotSetRecord:
    snapshot_set_id: str
    repo: str
    allowed_refs: List[str]
    allowed_snapshot_ids: List[str]
    allowed_head_shas: List[str]
    description: str
    created_utc: str
    updated_utc: str
    is_active: bool

    def as_props(self) -> Dict[str, Any]:
        return {
            "snapshot_set_id": self.snapshot_set_id,
            "repo": self.repo,
            "allowed_refs": self.allowed_refs,
            "allowed_snapshot_ids": self.allowed_snapshot_ids,
            "allowed_head_shas": self.allowed_head_shas,
            "description": self.description,
            "created_utc": self.created_utc,
            "updated_utc": self.updated_utc,
            "is_active": self.is_active,
        }


def _normalize_list(xs: Optional[Sequence[str]]) -> List[str]:
    if not xs:
        return []
    out: List[str] = []
    for x in xs:
        s = str(x).strip()
        if not s:
            continue
        out.append(s)
    # Stable, deterministic ordering + de-dupe
    return sorted(dict.fromkeys(out))


def _filter_for_ref(ref: str) -> Filter:
    """
    Same ref might be stored in different fields depending on importer args.
    Match ANY of:
      - tag == ref
      - ref_name == ref
      - branch == ref
    """
    return Filter.any_of(
        [
            Filter.by_property("tag").equal(ref),
            Filter.by_property("ref_name").equal(ref),
            Filter.by_property("branch").equal(ref),
        ]
    )


def resolve_refs_to_snapshot_ids(
    client: "weaviate.WeaviateClient",
    *,
    repo: str,
    refs: Sequence[str],
) -> Dict[str, str]:
    """
    Resolve each ref (branch/tag label) to an immutable snapshot_id using ImportRun.

    Strategy:
    - Find ImportRun where (tag==ref OR ref_name==ref OR branch==ref)
      AND repo==repo AND status=="completed"
    - Take the most recently finished if multiple exist.
    """
    coll = client.collections.use(COL_IMPORT)

    out: Dict[str, str] = {}
    for ref in refs:
        filters = Filter.all_of(
            [
                Filter.by_property("repo").equal(repo),
                Filter.by_property("status").equal("completed"),
                _filter_for_ref(ref),
            ]
        )

        res = coll.query.fetch_objects(
            filters=filters,
            limit=10,
            return_properties=["snapshot_id", "head_sha", "finished_utc", "started_utc", "tag", "ref_name", "branch"],
        )

        if not res.objects:
            raise RuntimeError(
                f"Cannot resolve ref '{ref}' to snapshot_id via ImportRun (repo={repo}). "
                f"Import the bundle first, or pass --snapshot-ids explicitly."
            )

        def key(o: wvc.data.DataObject) -> str:
            p = o.properties or {}
            return str(p.get("finished_utc") or p.get("started_utc") or "")

        best = sorted(res.objects, key=key, reverse=True)[0]
        props = best.properties or {}
        snapshot_id = str(props.get("snapshot_id") or "").strip()
        if not snapshot_id:
            # Fallback to head_sha if snapshot_id is missing (legacy imports).
            snapshot_id = str(props.get("head_sha") or "").strip()
        if not snapshot_id:
            raise RuntimeError(f"ImportRun record for ref '{ref}' has empty snapshot_id (repo={repo}).")

        out[ref] = snapshot_id

    return out


def upsert_snapshot_set(client: "weaviate.WeaviateClient", rec: SnapshotSetRecord) -> None:
    coll = client.collections.use(COL_SET)
    uuid = generate_uuid5(f"snapshotset::{rec.repo}::{rec.snapshot_set_id}")
    try:
        # self_provided vectors require a vector; dimension is irrelevant for metadata-only usage
        coll.data.insert(uuid=uuid, properties=rec.as_props(), vector=[0.0])
    except Exception:
        coll.data.update(uuid=uuid, properties=rec.as_props())


def fetch_snapshot_set(client: "weaviate.WeaviateClient", *, snapshot_set_id: str) -> Optional[Dict[str, Any]]:
    coll = client.collections.use(COL_SET)
    filters = Filter.by_property("snapshot_set_id").equal(snapshot_set_id)

    res = coll.query.fetch_objects(
        filters=filters,
        limit=1,
        return_properties=[
            "snapshot_set_id",
            "repo",
            "allowed_refs",
            "allowed_snapshot_ids",
            "allowed_head_shas",
            "description",
            "created_utc",
            "updated_utc",
            "is_active",
        ],
    )
    if not res.objects:
        return None
    props = res.objects[0].properties or {}
    return {k: props.get(k) for k in props.keys()}


def list_snapshot_sets(client: "weaviate.WeaviateClient", *, repo: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    coll = client.collections.use(COL_SET)

    filters: Optional[Filter] = None
    if repo.strip():
        filters = Filter.by_property("repo").equal(repo.strip())

    res = coll.query.fetch_objects(
        filters=filters,
        limit=limit,
        return_properties=[
            "snapshot_set_id",
            "repo",
            "allowed_refs",
            "allowed_snapshot_ids",
            "allowed_head_shas",
            "description",
            "created_utc",
            "updated_utc",
            "is_active",
        ],
    )

    items: List[Dict[str, Any]] = []
    for o in res.objects:
        p = o.properties or {}
        items.append({k: p.get(k) for k in p.keys()})

    items.sort(key=lambda x: (str(x.get("repo") or ""), str(x.get("snapshot_set_id") or "")))
    return items


def delete_snapshot_set(client: "weaviate.WeaviateClient", *, snapshot_set_id: str, repo: Optional[str] = None) -> bool:
    rec = fetch_snapshot_set(client, snapshot_set_id=snapshot_set_id)
    if rec is None:
        return False

    actual_repo = str(rec.get("repo") or "").strip()
    if repo and repo.strip() and repo.strip() != actual_repo:
        raise RuntimeError(f"SnapshotSet '{snapshot_set_id}' belongs to repo '{actual_repo}', not '{repo.strip()}'.")

    uuid = generate_uuid5(f"snapshotset::{actual_repo}::{snapshot_set_id}")
    coll = client.collections.use(COL_SET)
    coll.data.delete_by_id(uuid)
    return True


def _list_import_runs(
    client: "weaviate.WeaviateClient",
    *,
    repo: str = "",
    limit: int = 200,
) -> List[Dict[str, Any]]:
    coll = client.collections.use(COL_IMPORT)

    filters: Filter = Filter.by_property("status").equal("completed")
    if repo.strip():
        filters = Filter.all_of([filters, Filter.by_property("repo").equal(repo.strip())])

    res = coll.query.fetch_objects(
        filters=filters,
        limit=limit,
        return_properties=[
            "repo",
            "branch",
            "tag",
            "ref_type",
            "ref_name",
            "snapshot_id",
            "head_sha",
            "friendly_name",
            "status",
            "started_utc",
            "finished_utc",
        ],
    )

    items: List[Dict[str, Any]] = []
    for o in res.objects:
        p = o.properties or {}
        items.append({k: p.get(k) for k in p.keys()})

    def sort_key(x: Dict[str, Any]) -> Tuple[str, str]:
        # Newest first (string ISO is fine here)
        fin = str(x.get("finished_utc") or "")
        sta = str(x.get("started_utc") or "")
        return (fin or sta, sta)

    items.sort(key=sort_key, reverse=True)
    return items


def _kind_match(p: Dict[str, Any], kind: str) -> bool:
    kind = (kind or "all").strip().lower()
    if kind in ("", "all"):
        return True
    if kind == "tag":
        return bool(str(p.get("tag") or "").strip())
    if kind == "branch":
        return bool(str(p.get("branch") or "").strip())
    if kind in ("ref", "ref_name"):
        return bool(str(p.get("ref_name") or "").strip())
    return True


def _parse_select_numbers(raw: str, max_n: int) -> List[int]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\s]+", raw)
    out: List[int] = []
    for part in parts:
        if not part:
            continue
        if not re.match(r"^\d+$", part):
            raise ValueError(f"Invalid selection token: {part!r}")
        n = int(part)
        if n < 1 or n > max_n:
            raise ValueError(f"Selection out of range: {n} (valid 1..{max_n})")
        out.append(n)
    # Keep order, de-dupe
    seen = set()
    uniq: List[int] = []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _suggest_snapshot_set_id(repo: str, labels: List[str]) -> str:
    repo_part = _sanitize_id_part(repo) or "repo"
    label_parts = [_sanitize_id_part(x) for x in labels if _sanitize_id_part(x)]
    if not label_parts:
        return f"{repo_part}_set"
    joined = "_".join(label_parts[:4])
    return f"{repo_part}_{joined}"


def _cmd_list(args: argparse.Namespace) -> int:
    client = connect_weaviate(
        args.weaviate_host, args.weaviate_http_port, args.weaviate_grpc_port, api_key=args.weaviate_api_key
    )
    try:
        ensure_schema(client)
        items = list_snapshot_sets(client, repo=args.repo or "", limit=args.limit)
        if args.format == "json":
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:
            if not items:
                print("(no SnapshotSets)")
                return 0
            for it in items:
                sid = it.get("snapshot_set_id")
                r = it.get("repo")
                refs = it.get("allowed_refs") or []
                snapshot_ids = it.get("allowed_snapshot_ids") or []
                legacy_shas = it.get("allowed_head_shas") or []
                active = it.get("is_active")
                print(
                    f"- repo={r}  active={active}  refs={len(refs)}  snapshot_ids={len(snapshot_ids)}  legacy_shas={len(legacy_shas)}"
                )
                print(f"  id: {sid}")
            if args.details:
                print("")
                for it in items:
                    print(json.dumps(it, ensure_ascii=False, indent=2))
        return 0
    finally:
        client.close()


def _cmd_show(args: argparse.Namespace) -> int:
    client = connect_weaviate(
        args.weaviate_host, args.weaviate_http_port, args.weaviate_grpc_port, api_key=args.weaviate_api_key
    )
    try:
        ensure_schema(client)
        rec = fetch_snapshot_set(client, snapshot_set_id=args.id)
        if rec is None:
            print("NOT FOUND")
            return 2
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0
    finally:
        client.close()


def _cmd_add(args: argparse.Namespace) -> int:
    snapshot_set_id = args.id.strip()
    if not snapshot_set_id:
        raise SystemExit("--id is required")

    repo = args.repo.strip()
    if not repo:
        raise SystemExit("--repo is required")

    refs = _normalize_list(args.refs)
    snapshot_ids = _normalize_list(args.snapshot_ids)
    head_shas = _normalize_list(args.head_shas)

    if not refs and not snapshot_ids and not head_shas:
        raise SystemExit("Provide --refs and/or --snapshot-ids (or legacy --head-shas)")

    client = connect_weaviate(
        args.weaviate_host, args.weaviate_http_port, args.weaviate_grpc_port, api_key=args.weaviate_api_key
    )
    try:
        ensure_schema(client)

        resolved: Dict[str, str] = {}
        if refs:
            resolved = resolve_refs_to_snapshot_ids(client, repo=repo, refs=refs)

        merged_snapshot_ids = _normalize_list(list(resolved.values()) + snapshot_ids + head_shas)

        now = utc_now_iso()
        existing = fetch_snapshot_set(client, snapshot_set_id=snapshot_set_id)
        created = now if existing is None else str(existing.get("created_utc") or now)

        rec = SnapshotSetRecord(
            snapshot_set_id=snapshot_set_id,
            repo=repo,
            allowed_refs=refs,
            allowed_snapshot_ids=merged_snapshot_ids,
            allowed_head_shas=head_shas,
            description=str(args.description or "").strip(),
            created_utc=created,
            updated_utc=now,
            is_active=not bool(args.inactive),
        )

        upsert_snapshot_set(client, rec)
        print("OK")
        print(json.dumps(rec.as_props(), ensure_ascii=False, indent=2))
        return 0
    finally:
        client.close()


def _cmd_delete(args: argparse.Namespace) -> int:
    client = connect_weaviate(
        args.weaviate_host, args.weaviate_http_port, args.weaviate_grpc_port, api_key=args.weaviate_api_key
    )
    try:
        ensure_schema(client)
        ok = delete_snapshot_set(client, snapshot_set_id=args.id.strip(), repo=args.repo)
        print("DELETED" if ok else "NOT FOUND")
        return 0 if ok else 2
    finally:
        client.close()


def _cmd_snapshots(args: argparse.Namespace) -> int:
    """
    Discover imported snapshots (ImportRun rows), print them numbered, and optionally
    create a SnapshotSet from selected numbers.

    Behavior:
    - If --select is provided: create SnapshotSet immediately (no prompt).
    - If --select is missing and stdin is a TTY: prompt for "1,2" (or empty to exit).
    - If selection spans multiple repos: fail-fast (SnapshotSet has single 'repo').
    """
    client = connect_weaviate(
        args.weaviate_host, args.weaviate_http_port, args.weaviate_grpc_port, api_key=args.weaviate_api_key
    )
    try:
        ensure_schema(client)

        raw_items = _list_import_runs(client, repo=args.repo or "", limit=args.limit)
        items = [x for x in raw_items if _kind_match(x, args.kind)]

        if args.format == "json":
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0

        if not items:
            print("(no imported snapshots found)")
            return 0

        # Print numbered list
        for i, p in enumerate(items, start=1):
            repo = str(p.get("repo") or "").strip()
            snapshot_id = str(p.get("snapshot_id") or "").strip()
            head_sha = str(p.get("head_sha") or "").strip()
            label = _choose_ref_label(p)
            fin = str(p.get("finished_utc") or p.get("started_utc") or "")
            kind = "tag" if str(p.get("tag") or "").strip() else ("branch" if str(p.get("branch") or "").strip() else "ref")
            sid = snapshot_id or head_sha
            print(f"{i:>3}. repo={repo}  {kind}={label}  snapshot_id={sid[:12]}...  finished={fin}")

        max_n = len(items)

        select_raw = (args.select or "").strip()
        if not select_raw:
            if not sys.stdin.isatty():
                # Non-interactive, nothing else to do
                return 0
            select_raw = input("\nSelect snapshots by number (e.g. 1,2) or ENTER to exit: ").strip()
            if not select_raw:
                return 0

        try:
            selected_nums = _parse_select_numbers(select_raw, max_n=max_n)
        except Exception as e:
            raise SystemExit(f"Invalid selection: {e}") from e

        selected = [items[n - 1] for n in selected_nums]

        repos = sorted({str(p.get("repo") or "").strip() for p in selected if str(p.get("repo") or "").strip()})
        if len(repos) != 1:
            raise SystemExit(
                f"Selection spans multiple repos: {repos}. "
                f"SnapshotSet must belong to a single repo. Re-run with --repo <name> or select within one repo."
            )
        repo = repos[0]

        labels = [_choose_ref_label(p) for p in selected]
        snapshot_ids = _normalize_list(
            [
                str(p.get("snapshot_id") or p.get("head_sha") or "").strip()
                for p in selected
                if str(p.get("snapshot_id") or p.get("head_sha") or "").strip()
            ]
        )
        allowed_refs = _normalize_list(labels)

        suggested_id = _suggest_snapshot_set_id(repo, labels)
        snapshot_set_id = (args.id or "").strip()

        if not snapshot_set_id:
            if sys.stdin.isatty() and not (args.select or "").strip():
                raw = input(f"SnapshotSet id [{suggested_id}]: ").strip()
                snapshot_set_id = raw or suggested_id
            else:
                snapshot_set_id = suggested_id

        snapshot_set_id = _sanitize_id_part(snapshot_set_id) or suggested_id

        desc = (args.description or "").strip()
        if not desc and sys.stdin.isatty() and not (args.select or "").strip():
            raw = input("Description [optional]: ").strip()
            desc = raw

        now = utc_now_iso()
        existing = fetch_snapshot_set(client, snapshot_set_id=snapshot_set_id)
        created = now if existing is None else str(existing.get("created_utc") or now)

        rec = SnapshotSetRecord(
            snapshot_set_id=snapshot_set_id,
            repo=repo,
            allowed_refs=allowed_refs,
            allowed_snapshot_ids=snapshot_ids,
            allowed_head_shas=[],
            description=desc,
            created_utc=created,
            updated_utc=now,
            is_active=not bool(args.inactive),
        )

        upsert_snapshot_set(client, rec)
        print("\nOK (SnapshotSet created/updated)")
        print(json.dumps(rec.as_props(), ensure_ascii=False, indent=2))
        return 0
    finally:
        client.close()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage SnapshotSets in Weaviate.")
    p.add_argument("--weaviate-host", default="", help="Optional. Default from config/env.")
    p.add_argument("--weaviate-http-port", type=int, default=0, help="Optional. Default from config/env.")
    p.add_argument("--weaviate-grpc-port", type=int, default=0, help="Optional. Default from config/env.")
    p.add_argument(
        "--weaviate-api-key",
        default="",
        help="Optional. Overrides env/config. Prefer WEAVIATE_API_KEY env in production.",
    )
    p.add_argument(
        "--env",
        action="store_true",
        help="Load .env from project root before reading config/env (does not override existing env vars).",
    )
    p.add_argument(
        "--verbose",
        action="count",
        default=0,
        help="Be noisy. Use -v for INFO, -vv for DEBUG (suppresses httpx chatter by default).",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List SnapshotSets")
    p_list.add_argument("--repo", default="", help="Optional repo filter")
    p_list.add_argument("--limit", type=int, default=200)
    p_list.add_argument("--format", choices=["text", "json"], default="text")
    p_list.add_argument("--details", action="store_true", help="Print full JSON entries after summary")
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="Show SnapshotSet details")
    p_show.add_argument("--id", required=True, help="snapshot_set_id")
    p_show.set_defaults(func=_cmd_show)

    p_add = sub.add_parser("add", help="Create or update a SnapshotSet")
    p_add.add_argument("--id", required=True, help="snapshot_set_id")
    p_add.add_argument("--repo", required=True, help="repo name (must match ImportRun.repo)")
    p_add.add_argument("--refs", nargs="*", default=[], help="Allowed branch/tag refs (resolved to snapshot_id via ImportRun)")
    p_add.add_argument(
        "--snapshot-ids", nargs="*", default=[], help="Allowed immutable snapshot_id values (merged with resolved refs)"
    )
    # Legacy compatibility (head_sha -> snapshot_id)
    p_add.add_argument(
        "--head-shas", nargs="*", default=[], help="(Legacy) Allowed immutable head_sha values (merged with resolved refs)"
    )
    p_add.add_argument("--description", default="", help="Optional description")
    p_add.add_argument("--inactive", action="store_true", help="Create/update as inactive")
    p_add.set_defaults(func=_cmd_add)

    p_del = sub.add_parser("delete", help="Delete a SnapshotSet")
    p_del.add_argument("--id", required=True, help="snapshot_set_id")
    p_del.add_argument("--repo", default="", help="Optional. Safety check: expected repo")
    p_del.set_defaults(func=_cmd_delete)

    p_snap = sub.add_parser(
        "snapshots",
        help="List imported snapshots (ImportRun) and optionally create a SnapshotSet by selecting numbers.",
    )
    p_snap.add_argument("--repo", default="", help="Optional repo filter (if omitted: show all repos)")
    p_snap.add_argument("--kind", choices=["all", "branch", "tag", "ref_name"], default="all", help="Optional kind filter")
    p_snap.add_argument("--limit", type=int, default=200)
    p_snap.add_argument("--format", choices=["text", "json"], default="text")
    p_snap.add_argument("--select", default="", help="Selection by numbers, e.g. '1,2'. If omitted: interactive prompt.")
    p_snap.add_argument("--id", default="", help="SnapshotSet id (if omitted: suggested and optionally prompted).")
    p_snap.add_argument("--description", default="", help="Optional description (prompted if interactive and empty).")
    p_snap.add_argument("--inactive", action="store_true", help="Create/update as inactive")
    p_snap.set_defaults(func=_cmd_snapshots)

    return p


def _configure_logging(verbose_count: int) -> None:
    # Default: quiet (WARNING), because CLI should not spam.
    if verbose_count >= 2:
        level = logging.DEBUG
    elif verbose_count >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Suppress noisy libs unless verbose.
    if verbose_count == 0:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("weaviate").setLevel(logging.WARNING)


def main() -> int:
    args = build_arg_parser().parse_args()

    # Optional: load .env for this CLI process (does not override existing env vars).
    if getattr(args, "env", False):
        load_dotenv(PROJECT_ROOT / ".env", override=False)

    _configure_logging(int(getattr(args, "verbose", 0) or 0))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
