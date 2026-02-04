from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import json

import pytest
import weaviate

from code_query_engine.pipeline.actions.expand_dependency_tree import ExpandDependencyTreeAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.weaviate_graph_provider import WeaviateGraphProvider
from code_query_engine.pipeline.state import PipelineState
from server.snapshots.snapshot_registry import SnapshotRegistry


@dataclass(frozen=True)
class GraphCase:
    case_id: str
    allowlist: tuple[str, ...]
    seed_file: str
    expected_sql_names: tuple[str, ...]
    expected_edge_types: tuple[str, ...]


_GRAPH_CASES: list[GraphCase] = [
    GraphCase(
        case_id="allowlist:full",
        allowlist=(
            "ReadsFrom",
            "WritesTo",
            "Calls",
            "Executes",
            "FK",
            "On",
            "SynonymFor",
            "ReferencedBy(C#)",
        ),
        seed_file="db/procs/proc_ProcessPayment.sql",
        expected_sql_names=(
            "proc_ProcessPayment",
            "table_Payments",
            "proc_ValidateToken",
            "proc_ComputeFraudRisk",
            "table_Tokens",
            "table_AclRecords",
        ),
        expected_edge_types=("WritesTo", "Executes", "ReadsFrom"),
    ),
    GraphCase(
        case_id="allowlist:reads_writes_calls",
        allowlist=("ReadsFrom", "WritesTo", "Calls"),
        seed_file="db/procs/proc_ProcessPayment.sql",
        expected_sql_names=("proc_ProcessPayment", "table_Payments"),
        expected_edge_types=("WritesTo",),
    ),
    GraphCase(
        case_id="allowlist:writes_only",
        allowlist=("WritesTo",),
        seed_file="db/procs/proc_ProcessPayment.sql",
        expected_sql_names=("proc_ProcessPayment", "table_Payments"),
        expected_edge_types=("WritesTo",),
    ),
]

_GRAPH_REPORT_ROWS: list[dict[str, Any]] = []


class _History:
    def add_iteration(self, *_args, **_kwargs) -> None:
        return


class _TokenCounter:
    def count_tokens(self, text: str) -> int:
        return max(1, len((text or "").split()))


def _connect(env) -> weaviate.WeaviateClient:
    return weaviate.connect_to_local(
        host=env.weaviate_host,
        port=env.weaviate_http_port,
        grpc_port=env.weaviate_grpc_port,
    )


def _resolve_primary_snapshot(env) -> str:
    client = _connect(env)
    try:
        registry = SnapshotRegistry(client)
        snapshots = registry.list_snapshots(snapshot_set_id=env.snapshot_set_id, repository=env.repo_name)
        assert snapshots, "SnapshotSet does not contain snapshots."
        return snapshots[0].id
    finally:
        client.close()


def _find_canonical_id_by_source_file(
    *,
    client: weaviate.WeaviateClient,
    repository: str,
    snapshot_id: str,
    source_file: str,
) -> str:
    from weaviate.classes.query import Filter

    coll = client.collections.use("RagNode")
    filt = (
        Filter.by_property("repo").equal(repository)
        & Filter.by_property("snapshot_id").equal(snapshot_id)
        & Filter.by_property("source_file").equal(source_file)
    )
    res = coll.query.fetch_objects(
        filters=filt,
        limit=1,
        return_properties=["canonical_id"],
    )
    objs = list(res.objects or [])
    assert objs, f"Missing source_file in RagNode: {source_file}"
    cid = str((objs[0].properties or {}).get("canonical_id") or "").strip()
    assert cid, f"Missing canonical_id for source_file={source_file}"
    return cid


def _canonical_ids_for_sql_names(
    *,
    client: weaviate.WeaviateClient,
    repository: str,
    snapshot_id: str,
    sql_names: Iterable[str],
) -> list[str]:
    from weaviate.classes.query import Filter

    names = [str(x).strip() for x in sql_names if str(x).strip()]
    if not names:
        return []

    coll = client.collections.use("RagNode")
    filt = (
        Filter.by_property("repo").equal(repository)
        & Filter.by_property("snapshot_id").equal(snapshot_id)
        & Filter.by_property("sql_name").contains_any(names)
    )
    res = coll.query.fetch_objects(
        filters=filt,
        limit=max(len(names), 8),
        return_properties=["canonical_id", "sql_name"],
    )
    out = []
    for obj in res.objects or []:
        props = obj.properties or {}
        cid = str(props.get("canonical_id") or "").strip()
        if cid:
            out.append(cid)
    return out


def _run_expand(
    *,
    env,
    seed_nodes: list[str],
    edge_allowlist: list[str],
    graph_max_depth: int = 2,
    graph_max_nodes: int = 120,
    retrieval_filters: dict[str, Any] | None = None,
) -> PipelineState:
    client = _connect(env)
    try:
        state = PipelineState(
            user_query="dependency tree integration",
            session_id="it-expand-tree",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=_resolve_primary_snapshot(env),
        )
        state.retrieval_seed_nodes = list(seed_nodes)
        state.retrieval_filters = dict(retrieval_filters or {})

        runtime = PipelineRuntime(
            pipeline_settings={
                "repository": env.repo_name,
                "graph_max_depth": int(graph_max_depth),
                "graph_max_nodes": int(graph_max_nodes),
                "graph_edge_allowlist": list(edge_allowlist),
            },
            model=None,
            searcher=None,
            markdown_translator=None,
            translator_pl_en=None,
            history_manager=_History(),
            logger=None,
            constants=None,
            retrieval_backend=None,
            graph_provider=WeaviateGraphProvider(client=client),
            token_counter=_TokenCounter(),
            add_plant_link=lambda x, _consultant=None: x,
        )

        step = StepDef(
            id="expand",
            action="expand_dependency_tree",
            raw={
                "id": "expand",
                "action": "expand_dependency_tree",
                "max_depth_from_settings": "graph_max_depth",
                "max_nodes_from_settings": "graph_max_nodes",
                "edge_allowlist_from_settings": "graph_edge_allowlist",
            },
        )
        ExpandDependencyTreeAction().execute(step, state, runtime)
        return state
    finally:
        client.close()


def _edge_type_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in edges:
        t = str(e.get("edge_type") or "").strip() or "unknown"
        counts[t] = counts.get(t, 0) + 1
    return counts


def _append_graph_report_row(*, case: GraphCase, state: PipelineState, expected_ids: list[str]) -> None:
    edges = list(getattr(state, "graph_edges", []) or [])
    edge_types = _edge_type_counts(edges)
    _GRAPH_REPORT_ROWS.append(
        {
            "case_id": case.case_id,
            "seed_file": case.seed_file,
            "allowlist": list(case.allowlist),
            "seed_ids": list(getattr(state, "graph_seed_nodes", []) or []),
            "expected_node_ids": expected_ids,
            "observed_node_ids": list(getattr(state, "graph_expanded_nodes", []) or []),
            "observed_edges_preview": edges[:30],
            "edge_type_counts": edge_types,
        }
    )


@pytest.fixture(scope="session", autouse=True)
def _write_graph_report() -> None:
    yield
    if not _GRAPH_REPORT_ROWS:
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = Path("log") / "integration" / "retrival"
    out_dir.mkdir(parents=True, exist_ok=True)

    latest_path = out_dir / "graph_results_latest.log"
    archived_path = out_dir / f"graph_results_{ts}.log"

    lines: list[str] = [f"Generated UTC: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", ""]
    for i, row in enumerate(_GRAPH_REPORT_ROWS, start=1):
        lines.extend(
            [
                f"[{i}]",
                f"Case : {row.get('case_id')}",
                f"Seed file : {row.get('seed_file')}",
                f"Allowlist : {', '.join(row.get('allowlist') or [])}",
                f"Seed IDs : {', '.join(row.get('seed_ids') or [])}",
                f"Expected node IDs : {', '.join(row.get('expected_node_ids') or [])}",
                f"Observed node IDs : {', '.join(row.get('observed_node_ids') or [])}",
                f"Edge type counts : {json.dumps(row.get('edge_type_counts') or {}, sort_keys=True)}",
                "",
            ]
        )
    text = "\n".join(lines)
    latest_path.write_text(text, encoding="utf-8")
    archived_path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("case", _GRAPH_CASES, ids=[c.case_id for c in _GRAPH_CASES])
def test_dependency_tree_allowlist_expected_outputs(retrieval_integration_env, case: GraphCase) -> None:
    client = _connect(retrieval_integration_env)
    try:
        snapshot_id = _resolve_primary_snapshot(retrieval_integration_env)
        seed_id = _find_canonical_id_by_source_file(
            client=client,
            repository=retrieval_integration_env.repo_name,
            snapshot_id=snapshot_id,
            source_file=case.seed_file,
        )
        expected_ids = _canonical_ids_for_sql_names(
            client=client,
            repository=retrieval_integration_env.repo_name,
            snapshot_id=snapshot_id,
            sql_names=case.expected_sql_names,
        )
    finally:
        client.close()

    state = _run_expand(
        env=retrieval_integration_env,
        seed_nodes=[seed_id],
        edge_allowlist=list(case.allowlist),
    )
    _append_graph_report_row(case=case, state=state, expected_ids=expected_ids)

    observed_ids = set(state.graph_expanded_nodes or [])
    assert seed_id in observed_ids, "Seed node missing from expanded graph nodes."
    for expected in expected_ids:
        assert expected in observed_ids, f"Expected node id missing from expanded graph: {expected}"

    edge_types = {str(e.get('edge_type') or '').strip() for e in (state.graph_edges or []) if isinstance(e, dict)}
    edge_types = {t for t in edge_types if t}
    allow = {a.lower() for a in case.allowlist}
    normalized = set()
    for t in edge_types:
        tl = t.lower()
        if tl.startswith("sql_") or tl.startswith("cs_"):
            tl = tl.split("_", 1)[1]
        normalized.add(tl)
    disallowed = {t for t in normalized if t not in allow}
    assert not disallowed, f"Found disallowed edge types: {sorted(disallowed)}"
