#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reproduce Weaviate gRPC BM25 behavior (operator None/AND/OR) with tenant + filters.

Goal: quickly isolate whether timeouts/500s are caused by:
- gRPC deadline / client config
- BM25 operator AND/OR behavior
- filter composition

Example:
  python tools/repro_weaviate_grpc_bm25.py \\
    --tenant 0317701f-8103-5146-bbe9-4cedd73365f4 \\
    --repo nopCommerce \\
    --data-type regular_code \\
    --query "class Category location in codebase"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional


def _env(name: str, default: str) -> str:
    v = str(os.getenv(name, "") or "").strip()
    return v if v else default


def _env_int(name: str, default: int) -> int:
    v = str(os.getenv(name, "") or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _import_filter() -> Any:
    # weaviate-client v4
    try:
        from weaviate.classes.query import Filter  # type: ignore

        return Filter
    except Exception as e:
        raise RuntimeError("Cannot import weaviate.classes.query.Filter; check weaviate-client version") from e


def _make_operator(kind: str) -> Optional[Any]:
    k = (kind or "none").strip().lower()
    if k in ("none", "null", "no", "off"):
        return None

    try:
        from weaviate.collections.classes.grpc import BM25OperatorFactory  # type: ignore
    except Exception:
        # Operator factory missing in this client version.
        return None

    if k == "and":
        return BM25OperatorFactory.and_()
    if k == "or":
        return BM25OperatorFactory.or_(minimum_match=1)
    return None


def _build_where(*, repo: str, data_type: str, include_repo: bool, include_data_type: bool) -> Any:
    Filter = _import_filter()
    f = None
    if include_repo and repo.strip():
        f = Filter.by_property("repo").equal(repo.strip())
    if include_data_type and data_type.strip():
        g = Filter.by_property("data_type").equal(data_type.strip())
        f = g if f is None else (f & g)
    return f


def _run_one(
    *,
    collection: Any,
    tenant: str,
    query: str,
    limit: int,
    where_filter: Any,
    operator_kind: str,
    query_properties: Optional[list[str]],
) -> None:
    op = _make_operator(operator_kind)
    t0 = time.time()
    try:
        res = collection.query.bm25(
            query=query,
            query_properties=query_properties,
            operator=op,
            limit=limit,
            filters=where_filter,
            return_properties=["canonical_id"],
        )
        objs = list(getattr(res, "objects", []) or [])
        dt_ms = int((time.time() - t0) * 1000)
        first = None
        if objs:
            props = getattr(objs[0], "properties", None) or {}
            first = props.get("canonical_id")
        print(
            f"bm25 operator={operator_kind:>4} tenant={tenant} hits={len(objs)} dt_ms={dt_ms} first={first!r}"
        )
    except Exception as e:
        dt_ms = int((time.time() - t0) * 1000)
        print(
            f"bm25 operator={operator_kind:>4} tenant={tenant} ERROR={type(e).__name__}: {e} dt_ms={dt_ms}"
        )


def main() -> int:
    # When this script is executed as `python tools/...py`, sys.path[0] points to `tools/`.
    # That directory contains `tools/weaviate/`, which would shadow the external `weaviate` client package.
    # Ensure repo root is on sys.path and remove tools/ from import resolution.
    repo_root = Path(__file__).resolve().parents[1]
    tools_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(repo_root))
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != tools_dir]

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=_env("WEAVIATE_HOST", "localhost"))
    ap.add_argument("--http-port", type=int, default=_env_int("WEAVIATE_HTTP_PORT", 18080))
    ap.add_argument("--grpc-port", type=int, default=_env_int("WEAVIATE_GRPC_PORT", 15005))
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--collection", default="RagNode")
    ap.add_argument("--repo", default="nopCommerce")
    ap.add_argument("--data-type", default="regular_code")
    ap.add_argument("--query", default="class Category location in codebase")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--no-repo-filter", action="store_true")
    ap.add_argument("--no-data-type-filter", action="store_true")
    args = ap.parse_args()

    from vector_db.weaviate_client import create_client, get_settings

    settings = get_settings(
        overrides={
            "host": args.host,
            "http_port": args.http_port,
            "grpc_port": args.grpc_port,
        }
    )
    client = create_client(settings)
    try:
        coll = client.collections.get(args.collection).with_tenant(args.tenant)

        where_filter = _build_where(
            repo=args.repo,
            data_type=args.data_type,
            include_repo=not args.no_repo_filter,
            include_data_type=not args.no_data_type_filter,
        )

        query_props = [
            "text",
            "repo_relative_path",
            "source_file",
            "project_name",
            "class_name",
            "member_name",
            "symbol_type",
            "signature",
            "sql_kind",
            "sql_schema",
            "sql_name",
        ]

        print(
            f"connect host={args.host} http_port={args.http_port} grpc_port={args.grpc_port} "
            f"collection={args.collection} tenant={args.tenant}"
        )
        print(f"filters: repo={args.repo!r} include_repo={not args.no_repo_filter} data_type={args.data_type!r} include_data_type={not args.no_data_type_filter}")
        print(f"query: {args.query!r} limit={args.limit}")

        for kind in ("none", "and", "or"):
            _run_one(
                collection=coll,
                tenant=args.tenant,
                query=args.query,
                limit=int(args.limit),
                where_filter=where_filter,
                operator_kind=kind,
                query_properties=query_props,
            )
    finally:
        try:
            client.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
