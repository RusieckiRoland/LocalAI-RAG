#!/usr/bin/env python3
# tools/weaviate/create_import_container.py
#
# Production-grade ops script:
# - Ensures Weaviate collection "Imports" exists (no vectors).
# - Upserts an import record keyed by deterministic UUIDv5(repo + head_sha).
# - Validates inputs, supports retries, and supports fail-fast concurrency guard.
#
# Exit codes:
#   0  OK
#   2  validation error
#   3  weaviate connection / operation error
#   4  concurrency conflict (existing running import) unless --force
#
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from weaviate import connect_to_local
from weaviate.exceptions import WeaviateBaseError
from weaviate.classes.config import DataType, Property


# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)sZ [%(levelname)s] %(message)s",
)
log = logging.getLogger("weaviate-imports")


# ----------------------------
# Constants / Validation
# ----------------------------
_UUID_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # stable namespace
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")  # allow short or full SHA
_REF_TYPE_ALLOWED = {"branch", "tag", "commit"}
_STATUS_ALLOWED = {"running", "completed", "failed"}


@dataclass(frozen=True)
class WeaviateConn:
    host: str
    port: int
    grpc_port: int
    retries: int
    backoff_s: float


def _utc_now_rfc3339() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _short_sha(head_sha: str) -> str:
    s = head_sha.strip()
    return s[:8] if len(s) >= 8 else s


def _import_uuid(repo: str, head_sha: str) -> str:
    key = f"{repo}::{head_sha}"
    return str(uuid.uuid5(_UUID_NAMESPACE, key))


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"ENV {name} must be int, got: {val!r}")


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        raise ValueError(f"ENV {name} must be float, got: {val!r}")


def validate_inputs(
    *,
    repo: str,
    head_sha: str,
    ref_type: str,
    ref_name: str,
    branch_name: Optional[str],
    tag_name: Optional[str],
    status: str,
    objects_count: Optional[int],
    vectors_dim: Optional[int],
    imported_at_utc: Optional[str],
) -> None:
    if not repo.strip():
        raise ValueError("repo must be non-empty")

    hs = head_sha.strip()
    if not _SHA_RE.match(hs):
        raise ValueError("head_sha must look like a git SHA (7..40 hex chars)")

    if ref_type not in _REF_TYPE_ALLOWED:
        raise ValueError(f"ref_type must be one of {_REF_TYPE_ALLOWED}")

    if not ref_name.strip():
        raise ValueError("ref_name must be non-empty")

    if status not in _STATUS_ALLOWED:
        raise ValueError(f"status must be one of {_STATUS_ALLOWED}")

    if ref_type == "branch":
        if not (branch_name and branch_name.strip()):
            raise ValueError("ref_type=branch requires --branch")
        # tag is optional but usually empty here
    if ref_type == "tag":
        if not (tag_name and tag_name.strip()):
            raise ValueError("ref_type=tag requires --tag")
    if ref_type == "commit":
        # for commit, branch/tag should usually be empty, but we won't forbid it
        pass

    if objects_count is not None and objects_count < 0:
        raise ValueError("objects_count must be >= 0")

    if vectors_dim is not None and vectors_dim <= 0:
        raise ValueError("vectors_dim must be > 0")

    if imported_at_utc is not None:
        # Basic RFC3339 sanity; strict parsing is possible but avoid extra deps.
        if "T" not in imported_at_utc or not imported_at_utc.endswith("Z"):
            raise ValueError("imported_at_utc must look like RFC3339 and end with 'Z' (e.g. 2026-02-01T18:20:00Z)")


def with_retries(conn: WeaviateConn, fn, *, what: str) -> Any:
    last_err: Optional[BaseException] = None
    for attempt in range(1, conn.retries + 1):
        try:
            return fn()
        except (WeaviateBaseError, OSError, TimeoutError) as e:
            last_err = e
            if attempt == conn.retries:
                break
            sleep_s = conn.backoff_s * attempt
            log.warning("%s failed (attempt %d/%d): %s; retrying in %.1fs", what, attempt, conn.retries, e, sleep_s)
            time.sleep(sleep_s)
    raise last_err or RuntimeError(f"{what} failed")


def connect(conn: WeaviateConn):
    def _do():
        return connect_to_local(host=conn.host, port=conn.port, grpc_port=conn.grpc_port)
    return with_retries(conn, _do, what="connect_to_local")


def ensure_imports_collection(client) -> None:
    if client.collections.exists("Imports"):
        return

    client.collections.create(
        name="Imports",
        properties=[
            Property(name="imported_at_utc", data_type=DataType.DATE),
            Property(name="repo", data_type=DataType.TEXT),
            Property(name="head_sha", data_type=DataType.TEXT),

            Property(name="ref_type", data_type=DataType.TEXT),   # branch | tag | commit
            Property(name="ref_name", data_type=DataType.TEXT),   # develop | v1.2.3 | <shortsha>

            Property(name="branch_name", data_type=DataType.TEXT),
            Property(name="tag_name", data_type=DataType.TEXT),

            Property(name="friendly_name", data_type=DataType.TEXT),

            Property(name="status", data_type=DataType.TEXT),     # running | completed | failed
            Property(name="objects_count", data_type=DataType.INT),
            Property(name="vectors_dim", data_type=DataType.INT),

            # Store error details when status=failed (optional but extremely useful)
            Property(name="error_message", data_type=DataType.TEXT),
        ],
        vectorizer_config=None,  # no vectors for this collection
    )


def read_existing(col, record_uuid: str) -> Optional[Dict[str, Any]]:
    try:
        obj = col.data.get_by_id(record_uuid)
        if obj is None:
            return None
        # obj.properties is a dict
        return dict(obj.properties or {})
    except WeaviateBaseError:
        return None


def upsert_import_record(
    *,
    conn: WeaviateConn,
    repo: str,
    head_sha: str,
    ref_type: str,
    ref_name: str,
    branch_name: Optional[str],
    tag_name: Optional[str],
    status: str,
    objects_count: Optional[int],
    vectors_dim: Optional[int],
    imported_at_utc: Optional[str],
    error_message: Optional[str],
    force: bool,
) -> str:
    record_uuid = _import_uuid(repo, head_sha)
    friendly = tag_name.strip() if tag_name and tag_name.strip() else f"{repo}@{_short_sha(head_sha)}"

    def _do():
        client = connect(conn)
        try:
            ensure_imports_collection(client)
            col = client.collections.get("Imports")

            existing = read_existing(col, record_uuid)

            # Fail-fast concurrency guard:
            # If there is an existing running record and we're trying to write another running record, abort unless --force.
            if (
                not force
                and existing is not None
                and str(existing.get("status", "")).strip().lower() == "running"
                and status == "running"
            ):
                raise RuntimeError(
                    "concurrency_conflict: existing import is already running for this repo+head_sha. "
                    "Use --force to override."
                )

            props: Dict[str, Any] = {
                "imported_at_utc": imported_at_utc or (existing.get("imported_at_utc") if existing else None) or _utc_now_rfc3339(),
                "repo": repo,
                "head_sha": head_sha,

                "ref_type": ref_type,
                "ref_name": ref_name,

                "branch_name": (branch_name or "").strip(),
                "tag_name": (tag_name or "").strip(),

                "friendly_name": friendly,

                "status": status,
                "objects_count": int(objects_count) if objects_count is not None else (int(existing.get("objects_count", 0)) if existing else 0),
                "vectors_dim": int(vectors_dim) if vectors_dim is not None else (int(existing.get("vectors_dim", 0)) if existing else 0),
                "error_message": (error_message or "").strip(),
            }

            # Explicit upsert: insert if missing else update.
            if existing is None:
                col.data.insert(uuid=record_uuid, properties=props)
            else:
                # Update only properties; keep UUID stable.
                col.data.update(uuid=record_uuid, properties=props)

            return record_uuid
        finally:
            client.close()

    try:
        return with_retries(conn, _do, what="upsert_import_record")
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("concurrency_conflict:"):
            raise
        raise


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()

    ap.add_argument("--host", default=os.environ.get("WEAVIATE_HOST", "localhost"))
    ap.add_argument("--port", type=int, default=_env_int("WEAVIATE_PORT", 18080))
    ap.add_argument("--grpc-port", type=int, default=_env_int("WEAVIATE_GRPC_PORT", 15005))

    ap.add_argument("--retries", type=int, default=_env_int("WEAVIATE_RETRIES", 5))
    ap.add_argument("--backoff", type=float, default=_env_float("WEAVIATE_BACKOFF_S", 0.5))

    ap.add_argument("--repo", required=True)
    ap.add_argument("--head-sha", required=True)

    ap.add_argument("--ref-type", required=True, choices=["branch", "tag", "commit"])
    ap.add_argument("--ref-name", required=True)

    ap.add_argument("--branch", default=None)
    ap.add_argument("--tag", default=None)

    ap.add_argument("--status", default="running", choices=["running", "completed", "failed"])
    ap.add_argument("--objects-count", type=int, default=None)
    ap.add_argument("--vectors-dim", type=int, default=None)

    ap.add_argument("--imported-at-utc", default=None, help="RFC3339 timestamp ending with Z; default=now UTC")
    ap.add_argument("--error-message", default=None, help="Use with --status failed")

    ap.add_argument("--force", action="store_true", help="Override concurrency guard and overwrite running record")

    return ap.parse_args()


def main() -> int:
    args = parse_args()

    try:
        validate_inputs(
            repo=args.repo,
            head_sha=args.head_sha,
            ref_type=args.ref_type,
            ref_name=args.ref_name,
            branch_name=args.branch,
            tag_name=args.tag,
            status=args.status,
            objects_count=args.objects_count,
            vectors_dim=args.vectors_dim,
            imported_at_utc=args.imported_at_utc,
        )
    except ValueError as e:
        log.error("validation error: %s", e)
        return 2

    if args.status == "failed" and (args.error_message is None or not args.error_message.strip()):
        log.error("validation error: --status failed requires --error-message")
        return 2

    conn = WeaviateConn(
        host=args.host,
        port=int(args.port),
        grpc_port=int(args.grpc_port),
        retries=int(args.retries),
        backoff_s=float(args.backoff),
    )

    try:
        rec_uuid = upsert_import_record(
            conn=conn,
            repo=args.repo.strip(),
            head_sha=args.head_sha.strip(),
            ref_type=args.ref_type,
            ref_name=args.ref_name.strip(),
            branch_name=args.branch,
            tag_name=args.tag,
            status=args.status,
            objects_count=args.objects_count,
            vectors_dim=args.vectors_dim,
            imported_at_utc=args.imported_at_utc,
            error_message=args.error_message,
            force=bool(args.force),
        )
        log.info("OK: Imports record upserted uuid=%s repo=%s head_sha=%s ref=%s:%s status=%s",
                 rec_uuid, args.repo, _short_sha(args.head_sha), args.ref_type, args.ref_name, args.status)
        return 0

    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("concurrency_conflict:"):
            log.error("%s", msg)
            return 4
        log.error("operation error: %s", e)
        return 3

    except (WeaviateBaseError, OSError, TimeoutError) as e:
        log.error("weaviate error: %s", e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
