from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import weaviate

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.actions.search_nodes import SearchNodesAction
from code_query_engine.pipeline.actions.expand_dependency_tree import ExpandDependencyTreeAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend
from code_query_engine.pipeline.providers.weaviate_graph_provider import WeaviateGraphProvider
from code_query_engine.pipeline.state import PipelineState
from server.snapshots.snapshot_registry import SnapshotRegistry


@dataclass(frozen=True)
class QueryCase:
    corpus: str
    search_type: str
    query: str
    expected_sources: Tuple[str, ...]
    query_id: str


class _History:
    def add_iteration(self, *_args, **_kwargs) -> None:
        return


class _TokenCounter:
    def count_tokens(self, text: str) -> int:
        return max(1, len((text or "").split()))


def connect(env) -> weaviate.WeaviateClient:
    return weaviate.connect_to_local(
        host=env.weaviate_host,
        port=env.weaviate_http_port,
        grpc_port=env.weaviate_grpc_port,
    )


def resolve_snapshots(client: weaviate.WeaviateClient, env) -> Tuple[str, Optional[str]]:
    bundle_paths = list(getattr(env, "bundle_paths", None) or [])
    if bundle_paths:
        primary = _snapshot_id_from_bundle(bundle_paths[0])
        secondary = _snapshot_id_from_bundle(bundle_paths[1]) if len(bundle_paths) > 1 else None
        if primary:
            return primary, secondary or None

    refs = list(getattr(env, "imported_refs", None) or [])
    if refs:
        primary = _resolve_snapshot_id_for_ref(client, env.repo_name, refs[0])
        secondary = _resolve_snapshot_id_for_ref(client, env.repo_name, refs[1]) if len(refs) > 1 else None
        return primary, secondary or None

    registry = SnapshotRegistry(client)
    snapshots = registry.list_snapshots(snapshot_set_id=env.snapshot_set_id, repository=env.repo_name)
    assert snapshots, "SnapshotSet does not contain snapshots."
    primary = snapshots[0].id
    secondary = snapshots[1].id if len(snapshots) > 1 else None
    return primary, secondary


def _snapshot_id_from_bundle(bundle_path: Path) -> str:
    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = [n for n in zf.namelist() if n.endswith("repo_meta.json")]
            if not names:
                return ""
            meta = json.loads(zf.read(names[0]).decode("utf-8", errors="replace"))
            return str(meta.get("SnapshotId") or meta.get("snapshot_id") or "").strip()
    except Exception:
        return ""


def _resolve_snapshot_id_for_ref(client: weaviate.WeaviateClient, repo: str, ref: str) -> str:
    from weaviate.classes.query import Filter

    coll = client.collections.use("ImportRun")
    filters = Filter.all_of(
        [
            Filter.by_property("repo").equal(repo),
            Filter.by_property("status").equal("completed"),
            Filter.any_of(
                [
                    Filter.by_property("tag").equal(ref),
                    Filter.by_property("ref_name").equal(ref),
                    Filter.by_property("branch").equal(ref),
                ]
            ),
        ]
    )
    res = coll.query.fetch_objects(
        filters=filters,
        limit=10,
        return_properties=["snapshot_id", "head_sha", "finished_utc", "started_utc", "tag", "ref_name", "branch"],
    )
    if not res.objects:
        raise RuntimeError(f"Cannot resolve ref '{ref}' to snapshot_id via ImportRun (repo={repo}).")

    def key(obj: Any) -> str:
        p = obj.properties or {}
        return str(p.get("finished_utc") or p.get("started_utc") or "")

    best = sorted(res.objects, key=key, reverse=True)[0]
    props = best.properties or {}
    snapshot_id = str(props.get("snapshot_id") or "").strip()
    if not snapshot_id:
        snapshot_id = str(props.get("head_sha") or "").strip()
    if not snapshot_id:
        raise RuntimeError(f"ImportRun record for ref '{ref}' has empty snapshot_id (repo={repo}).")
    return snapshot_id


def build_runtime(*, client: weaviate.WeaviateClient, env, retrieval_backend: WeaviateRetrievalBackend, graph_provider: Optional[WeaviateGraphProvider] = None) -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings={
            "repository": env.repo_name,
            "max_context_tokens": 12000,
        },
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=_History(),
        logger=None,
        constants=None,
        retrieval_backend=retrieval_backend,
        graph_provider=graph_provider,
        token_counter=_TokenCounter(),
        add_plant_link=lambda x, _consultant=None: x,
    )


def run_search_and_fetch(*, env, case: QueryCase, retrieval_filters: Dict[str, Any]) -> PipelineState:
    client = connect(env)
    try:
        embed_model = os.getenv("INTEGRATION_EMBED_MODEL", "models/embedding/e5-base-v2").strip()
        # IMPORTANT: use round-specific permissions (do not rely on global config.json contents).
        backend = WeaviateRetrievalBackend(
            client=client,
            query_embed_model=embed_model,
            security_config=getattr(getattr(env, "round", None), "permissions", {}) or {},
        )
        primary, secondary = resolve_snapshots(client, env)

        def _sanitize_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
            out = dict(filters or {})
            permissions = getattr(env, "round", None)
            permissions = getattr(permissions, "permissions", {}) if permissions else {}
            if not bool(permissions.get("acl_enabled", True)):
                out.pop("acl_tags_any", None)
            if not bool(permissions.get("security_enabled", False)):
                out.pop("classification_labels_all", None)
                out.pop("user_level", None)
                out.pop("clearance_level", None)
                out.pop("doc_level_max", None)
            else:
                kind = str((permissions.get("security_model") or {}).get("kind") or "")
                if kind == "clearance_level":
                    out.pop("classification_labels_all", None)
                elif kind in ("labels_universe_subset", "classification_labels"):
                    out.pop("user_level", None)
                    out.pop("clearance_level", None)
                    out.pop("doc_level_max", None)
            labels = out.get("classification_labels_all")
            if isinstance(labels, list) and not [str(x).strip() for x in labels if str(x).strip()]:
                out.pop("classification_labels_all", None)
            acl_any = out.get("acl_tags_any")
            if isinstance(acl_any, list) and not [str(x).strip() for x in acl_any if str(x).strip()]:
                out.pop("acl_tags_any", None)
            return out

        state = PipelineState(
            user_query=case.query,
            session_id="it-search-fetch",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=primary,
            snapshot_id_b=secondary,
        )
        state.last_model_response = case.query
        state.retrieval_filters = _sanitize_filters(retrieval_filters or {})

        runtime = build_runtime(client=client, env=env, retrieval_backend=backend)
        setattr(runtime, "pipeline_trace_enabled", True)
        setattr(state, "pipeline_trace_events", [])

        search_step = StepDef(
            id="search_nodes",
            action="search_nodes",
            raw={
                "search_type": case.search_type,
                "query": case.query,
                "top_k": 5,
            },
        )
        SearchNodesAction().execute(search_step, state, runtime)

        fetch_step = StepDef(
            id="fetch_node_texts",
            action="fetch_node_texts",
            raw={
                "budget_tokens": 6000,
                "prioritization_mode": "seed_first",
            },
        )
        FetchNodeTextsAction().execute(fetch_step, state, runtime)

        return state
    finally:
        client.close()


def run_expand_dependency_tree(*, env, seed_ids: List[str], retrieval_filters: Dict[str, Any], allowlist: List[str], max_depth: int) -> PipelineState:
    client = connect(env)
    try:
        embed_model = os.getenv("INTEGRATION_EMBED_MODEL", "models/embedding/e5-base-v2").strip()
        backend = WeaviateRetrievalBackend(
            client=client,
            query_embed_model=embed_model,
            security_config=getattr(getattr(env, "round", None), "permissions", {}) or {},
        )
        graph_provider = WeaviateGraphProvider(client=client)
        primary, secondary = resolve_snapshots(client, env)

        state = PipelineState(
            user_query="",
            session_id="it-expand",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=primary,
            snapshot_id_b=secondary,
        )
        state.retrieval_seed_nodes = list(seed_ids or [])
        permissions = getattr(env, "round", None)
        permissions = getattr(permissions, "permissions", {}) if permissions else {}
        if not bool(permissions.get("acl_enabled", True)):
            retrieval_filters = dict(retrieval_filters or {})
            retrieval_filters.pop("acl_tags_any", None)
        state.retrieval_filters = dict(retrieval_filters or {})

        runtime = build_runtime(client=client, env=env, retrieval_backend=backend, graph_provider=graph_provider)

        expand_step = StepDef(
            id="expand_dependency_tree",
            action="expand_dependency_tree",
            raw={
                "max_depth_from_settings": "graph_max_depth",
                "max_nodes_from_settings": "graph_max_nodes",
                "edge_allowlist_from_settings": "edge_allowlist",
            },
        )
        runtime.pipeline_settings["graph_max_depth"] = max_depth
        runtime.pipeline_settings["graph_max_nodes"] = 200
        runtime.pipeline_settings["edge_allowlist"] = list(allowlist)

        ExpandDependencyTreeAction().execute(expand_step, state, runtime)
        return state
    finally:
        client.close()


def load_observed_sources(client: weaviate.WeaviateClient, state: PipelineState, repo_name: str) -> List[str]:
    ids = [str(x) for x in (state.retrieval_seed_nodes or []) if str(x).strip()]
    if not ids:
        return []
    try:
        from weaviate.classes.query import Filter
    except Exception:
        return []

    coll = client.collections.use("RagNode")
    f = (
        Filter.by_property("repo").equal(repo_name)
        & Filter.by_property("canonical_id").contains_any(ids)
    )
    res = coll.query.fetch_objects(filters=f, limit=len(ids), return_properties=["canonical_id", "source_file"])
    src_by_id: Dict[str, str] = {}
    for obj in res.objects or []:
        props = obj.properties or {}
        cid = str(props.get("canonical_id") or "").strip()
        src = str(props.get("source_file") or "").strip()
        if cid and src:
            src_by_id[cid] = src
    return [src_by_id[i] for i in ids if i in src_by_id]


def load_observed_docs(client: weaviate.WeaviateClient, state: PipelineState, repo_name: str) -> List[Dict[str, Any]]:
    ids = [str(x) for x in (state.retrieval_seed_nodes or []) if str(x).strip()]
    if not ids:
        return []
    try:
        from weaviate.classes.query import Filter
    except Exception:
        return []

    coll = client.collections.use("RagNode")
    props_in_schema: set[str] = set()
    try:
        cfg = coll.config.get()
        props_in_schema = {p.name for p in (cfg.properties or []) if p and p.name}
    except Exception:
        # Best-effort: if we cannot read schema, avoid requesting optional props.
        props_in_schema = set()

    base_props = ["canonical_id", "source_file"]
    optional_props = ["acl_allow", "classification_labels", "doc_level"]
    return_props = list(base_props)
    for prop in optional_props:
        if prop in props_in_schema:
            return_props.append(prop)

    f = (
        Filter.by_property("repo").equal(repo_name)
        & Filter.by_property("canonical_id").contains_any(ids)
    )
    res = coll.query.fetch_objects(
        filters=f,
        limit=len(ids),
        return_properties=return_props,
    )
    by_id: Dict[str, Dict[str, Any]] = {}
    for obj in res.objects or []:
        props = obj.properties or {}
        cid = str(props.get("canonical_id") or "").strip()
        if not cid:
            continue
        acl_vals = props.get("acl_allow") if "acl_allow" in return_props else []
        cls_vals = props.get("classification_labels") if "classification_labels" in return_props else []
        doc_level = props.get("doc_level") if "doc_level" in return_props else None
        by_id[cid] = (
            {
                "canonical_id": cid,
                "source_file": str(props.get("source_file") or "").strip(),
                "acl_allow": [str(x).strip() for x in (acl_vals or []) if str(x).strip()],
                "classification_labels": [str(x).strip() for x in (cls_vals or []) if str(x).strip()],
                "doc_level": doc_level,
            }
        )
    return [by_id[i] for i in ids if i in by_id]


def log_dir() -> Path:
    out = Path("log") / "integration" / "retrival"
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_named_log(*, stem: str, test_id: str, lines: Iterable[str]) -> Path:
    out_dir = log_dir()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", test_id.strip())[:64] or "test"
    archived = out_dir / f"{stem}_{ts}_{slug}.log"
    latest = out_dir / f"{stem}_latest.log"
    text = "\n".join(lines).rstrip() + "\n"
    archived.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return archived


def write_test_results_log(*, test_id: str, lines: Iterable[str]) -> Path:
    return write_named_log(stem="test_results", test_id=test_id, lines=lines)


def write_pipeline_trace(*, search_type: str, query: str, retrieval_filters: Dict[str, Any], observed_sources: List[str]) -> None:
    out_dir = log_dir() / "pipeline_traces"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", query.strip())[:64] or "query"
    path = out_dir / f"{ts}_{search_type}_{slug}.json"
    payload = {
        "generated_utc": ts,
        "query": query,
        "search_type": search_type,
        "retrieval_filters": retrieval_filters,
        "observed_sources": observed_sources,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_text(path: Path, text: str) -> None:
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")
    else:
        path.write_text(text, encoding="utf-8")


def parse_golden_results(path: Path) -> List[QueryCase]:
    raw = path.read_text(encoding="utf-8")
    corpus = ""
    cases: List[QueryCase] = []

    def item_to_source(corpus_name: str, item: str) -> str:
        idx = int(item)
        if corpus_name == "csharp":
            return f"src/FakeEnterprise.Corpus/CSharp/CorpusItem{idx:03d}.cs"
        return f"db/procs/proc_Corpus_{idx:03d}.sql"

    lines = raw.splitlines()
    query_id = ""
    query_text = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("## Corpus 1"):
            corpus = "csharp"
        elif line.startswith("## Corpus 2"):
            corpus = "sql"
        elif line.startswith("### Q"):
            m = re.match(r"###\s+Q(\d+)", line)
            query_id = f"Q{m.group(1)}" if m else ""
            query_text = ""
        elif line.startswith("**Query:**"):
            m = re.search(r"`(.+)`", line)
            query_text = m.group(1) if m else ""
        elif line.startswith("####") and "Top 5" in line:
            if not corpus or not query_text:
                i += 1
                continue
            method = ""
            if line.lower().startswith("#### bm25"):
                method = "bm25"
            elif line.lower().startswith("#### semantic"):
                method = "semantic"
            elif line.lower().startswith("#### hybrid"):
                method = "hybrid"
            if not method:
                i += 1
                continue
            # Skip to table rows
            items: List[str] = []
            j = i + 1
            while j < len(lines):
                row = lines[j].strip()
                if row == "":
                    if items:
                        break
                    j += 1
                    continue
                if row.startswith("|") and row.count("|") >= 4:
                    cols = [c.strip() for c in row.strip("|").split("|")]
                    if cols and cols[0].isdigit():
                        items.append(cols[1])
                j += 1
            expected_sources = tuple(item_to_source(corpus, item) for item in items)
            if expected_sources:
                cases.append(
                    QueryCase(
                        corpus=corpus,
                        search_type=method,
                        query=query_text,
                        expected_sources=expected_sources,
                        query_id=query_id,
                    )
                )
            i = j
            continue
        i += 1

    return cases


def load_bundle_metadata(bundle_path: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = zf.namelist()
        chunks_path = next((n for n in names if n.endswith("chunks.json")), "")
        sql_path = next((n for n in names if n.endswith("sql_bodies.jsonl")), "")

        if chunks_path:
            items = json.loads(zf.read(chunks_path).decode("utf-8"))
            for item in items:
                file = str(item.get("File") or "").strip()
                if not file:
                    continue
                out[file] = {
                    "acl": list(item.get("acl_tags_any") or []),
                    "labels": list(item.get("classification_labels_all") or []),
                    "clearance": item.get("clearance_level"),
                }

        if sql_path:
            lines = zf.read(sql_path).decode("utf-8").splitlines()
            for line in lines:
                if not line.strip():
                    continue
                item = json.loads(line)
                file = str(item.get("file") or "").strip()
                if not file:
                    continue
                out[file] = {
                    "acl": list(item.get("acl_tags_any") or []),
                    "labels": list(item.get("classification_labels_all") or []),
                    "clearance": item.get("clearance_level"),
                }

    return out


def is_visible(
    meta: Dict[str, Any],
    *,
    acl_any: List[str],
    labels_all: List[str],
    user_level: Optional[int],
    permissions: dict,
) -> bool:
    acl_enabled = bool(permissions.get("acl_enabled", True))
    security_enabled = bool(permissions.get("security_enabled", False))

    if acl_enabled and acl_any:
        doc_acl = [str(x).strip() for x in (meta.get("acl") or []) if str(x).strip()]
        if doc_acl and not set(doc_acl).intersection(set(acl_any)):
            return False

    if security_enabled:
        model = permissions.get("security_model") or {}
        kind = str(model.get("kind") or "")
        if kind == "clearance_level":
            doc_level = meta.get("clearance")
            allow_missing = bool(model.get("clearance_level", {}).get("allow_missing_doc_level", True))
            if doc_level is None:
                return allow_missing
            if user_level is None:
                return True
            return int(doc_level) <= int(user_level)
        if kind == "labels_universe_subset":
            doc_labels = [str(x).strip() for x in (meta.get("labels") or []) if str(x).strip()]
            allow_unlabeled = bool(model.get("labels_universe_subset", {}).get("allow_unlabeled", True))
            if not doc_labels:
                return allow_unlabeled
            return set(doc_labels).issubset(set(labels_all))

    return True
