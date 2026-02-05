from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import json

import pytest
import weaviate

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend
from code_query_engine.pipeline.state import PipelineState
from server.snapshots.snapshot_registry import SnapshotRegistry


@dataclass(frozen=True)
class FetchCase:
    case_id: str
    prioritization_mode: str
    seed_files: tuple[str, ...]
    graph_files: tuple[str, ...]
    graph_edges: tuple[tuple[str, str], ...]
    budget_tokens: int | None = None
    budget_tokens_from_settings: str | None = None
    max_chars: int | None = None


_FETCH_REPORT_ROWS: list[dict[str, Any]] = []


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


def _canonical_ids_for_sources(
    *,
    client: weaviate.WeaviateClient,
    repository: str,
    snapshot_id: str,
    source_files: Iterable[str],
) -> list[str]:
    out: list[str] = []
    for source in source_files:
        out.append(
            _find_canonical_id_by_source_file(
                client=client,
                repository=repository,
                snapshot_id=snapshot_id,
                source_file=source,
            )
        )
    return out


def _load_source_files(
    client: weaviate.WeaviateClient,
    repo: str,
    snapshot_id: str,
    node_ids: Iterable[str],
) -> dict[str, str]:
    from weaviate.classes.query import Filter

    ids = [str(x).strip() for x in node_ids if str(x).strip()]
    if not ids:
        return {}

    coll = client.collections.use("RagNode")
    filt = (
        Filter.by_property("repo").equal(repo)
        & Filter.by_property("snapshot_id").equal(snapshot_id)
        & Filter.by_property("canonical_id").contains_any(ids)
    )
    res = coll.query.fetch_objects(
        filters=filt,
        limit=max(len(ids), 8),
        return_properties=["canonical_id", "source_file"],
    )
    out: dict[str, str] = {}
    for obj in (res.objects or []):
        props = obj.properties or {}
        cid = str(props.get("canonical_id") or "").strip()
        src = str(props.get("source_file") or "").strip()
        if cid:
            out[cid] = src
    return out


def _token_counts(token_counter: _TokenCounter, texts: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for node_id, text in texts.items():
        out[node_id] = token_counter.count_tokens(text)
    return out


def _pick_atomic_skip_triplet(node_ids: list[str], token_counts: dict[str, int]) -> tuple[str, str, str]:
    candidates = [nid for nid in node_ids if nid in token_counts]
    if len(candidates) < 3:
        raise AssertionError("Need at least 3 candidates to build atomic skip case.")

    sorted_by_tokens = sorted(candidates, key=lambda nid: (token_counts.get(nid, 0), nid))
    a = sorted_by_tokens[0]
    b = sorted_by_tokens[-1]
    c = sorted_by_tokens[1] if len(sorted_by_tokens) > 2 else sorted_by_tokens[0]

    if a == b or b == c or a == c:
        raise AssertionError("Failed to pick distinct nodes for atomic skip case.")
    if token_counts.get(b, 0) <= token_counts.get(c, 0):
        raise AssertionError("Atomic skip requires middle node larger than last node.")

    return a, b, c


def _run_fetch(
    *,
    env,
    seed_ids: list[str],
    graph_ids: list[str],
    graph_edges: list[dict[str, Any]],
    budget_tokens: int | None,
    budget_tokens_from_settings: str | None,
    max_chars: int | None,
    prioritization_mode: str,
    settings_extra: dict[str, Any] | None = None,
) -> PipelineState:
    client = _connect(env)
    try:
        backend = WeaviateRetrievalBackend(client=client)
        snapshot_id = _resolve_primary_snapshot(env)

        state = PipelineState(
            user_query="fetch_node_texts integration",
            session_id="it-fetch-texts",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_id=snapshot_id,
            snapshot_set_id=env.snapshot_set_id,
        )
        state.retrieval_seed_nodes = list(seed_ids)
        state.graph_expanded_nodes = list(graph_ids)
        state.graph_edges = list(graph_edges)

        settings = {
            "repository": env.repo_name,
            "max_context_tokens": 12000,
        }
        if settings_extra:
            settings.update(settings_extra)

        runtime = PipelineRuntime(
            pipeline_settings=settings,
            model=None,
            searcher=None,
            markdown_translator=None,
            translator_pl_en=None,
            history_manager=_History(),
            logger=None,
            constants=None,
            retrieval_backend=backend,
            graph_provider=None,
            token_counter=_TokenCounter(),
            add_plant_link=lambda x, _consultant=None: x,
        )

        raw: dict[str, Any] = {
            "id": "fetch",
            "action": "fetch_node_texts",
            "prioritization_mode": prioritization_mode,
        }
        if budget_tokens is not None:
            raw["budget_tokens"] = int(budget_tokens)
        if budget_tokens_from_settings is not None:
            raw["budget_tokens_from_settings"] = budget_tokens_from_settings
        if max_chars is not None:
            raw["max_chars"] = int(max_chars)

        step = StepDef(
            id="fetch",
            action="fetch_node_texts",
            raw=raw,
        )
        FetchNodeTextsAction().execute(step, state, runtime)
        return state
    finally:
        client.close()


def _expected_seed_first_order(seed_ids: list[str], graph_ids: list[str], depth_map: dict[str, int]) -> list[str]:
    graph_only = [nid for nid in graph_ids if nid not in set(seed_ids)]
    graph_sorted = sorted(graph_only, key=lambda nid: (depth_map.get(nid, 999999), nid))
    return list(seed_ids) + graph_sorted


def _expected_balanced_order(seed_ids: list[str], graph_ids: list[str], depth_map: dict[str, int]) -> list[str]:
    graph_only = [nid for nid in graph_ids if nid not in set(seed_ids)]
    graph_sorted = sorted(graph_only, key=lambda nid: (depth_map.get(nid, 999999), nid))
    out: list[str] = []
    si = 0
    gi = 0
    while si < len(seed_ids) or gi < len(graph_sorted):
        if si < len(seed_ids):
            out.append(seed_ids[si])
            si += 1
        if gi < len(graph_sorted):
            out.append(graph_sorted[gi])
            gi += 1
    return out


def _expected_graph_first_order(
    seed_ids: list[str],
    graph_ids: list[str],
    depth_map: dict[str, int],
    parent_map: dict[str, str | None],
) -> list[str]:
    seed_set = set(seed_ids)
    graph_only = [nid for nid in graph_ids if nid not in seed_set]
    graph_sorted = sorted(graph_only, key=lambda nid: (depth_map.get(nid, 999999), nid))

    def _root_seed(node_id: str) -> str | None:
        cur = node_id
        guard = 0
        while guard < 10000:
            guard += 1
            p = parent_map.get(cur, None)
            if p is None:
                return cur if cur in seed_set else None
            cur = p
        return None

    descendants: dict[str, list[str]] = {s: [] for s in seed_ids}
    for node_id in graph_sorted:
        root = _root_seed(node_id)
        if root in descendants:
            descendants[root].append(node_id)

    ordered: list[str] = []
    for seed in seed_ids:
        ordered.append(seed)
        ordered.extend(descendants.get(seed, []))
    return ordered


def _build_depth_parent(seed_ids: list[str], graph_edges: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, str | None]]:
    depth: dict[str, int] = {}
    parent: dict[str, str | None] = {}

    if not graph_edges:
        for s in seed_ids:
            depth[s] = 0
            parent[s] = None
        return depth, parent

    adj: dict[str, list[str]] = {}
    for e in graph_edges:
        a = str(e.get("from_id") or "").strip()
        b = str(e.get("to_id") or "").strip()
        if not a or not b:
            continue
        adj.setdefault(a, []).append(b)

    q: list[str] = []
    seen: set[str] = set()
    for s in seed_ids:
        seen.add(s)
        depth[s] = 0
        parent[s] = None
        q.append(s)

    while q:
        cur = q.pop(0)
        cur_d = depth.get(cur, 0)
        for nxt in adj.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            depth[nxt] = cur_d + 1
            parent[nxt] = cur
            q.append(nxt)

    return depth, parent


def _append_fetch_report_row(*, case_id: str, state: PipelineState, expected_order: list[str], source_map: dict[str, str]) -> None:
    node_texts = list(state.node_texts or [])
    observed_order = [str(item.get("id") or "") for item in node_texts if isinstance(item, dict)]
    graph_debug = getattr(state, "graph_debug", None)
    if not isinstance(graph_debug, dict):
        graph_debug = {}
    _FETCH_REPORT_ROWS.append(
        {
            "case_id": case_id,
            "prioritization_mode": str(graph_debug.get("prioritization_mode") or ""),
            "seed_ids": list(getattr(state, "retrieval_seed_nodes", []) or []),
            "graph_ids": list(getattr(state, "graph_expanded_nodes", []) or []),
            "expected_order": expected_order,
            "observed_order": observed_order,
            "observed_sources": [source_map.get(x, "") for x in observed_order],
            "graph_debug": dict(graph_debug),
            "materialization_debug": dict(getattr(state, "_fetch_node_texts_debug", {}) or {}),
        }
    )


@pytest.fixture(scope="session", autouse=True)
def _write_fetch_report() -> None:
    yield
    if not _FETCH_REPORT_ROWS:
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = Path("log") / "integration" / "retrival"
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    detailed_path = out_dir / "fetch_texts_results_latest.log"
    detailed_archived = out_dir / f"fetch_texts_results_{ts}.log"

    lines: list[str] = [
        f"Generated UTC: {generated_utc}",
        "",
    ]
    for i, row in enumerate(_FETCH_REPORT_ROWS, start=1):
        expected = "; ".join(row.get("expected_order") or [])
        observed = "; ".join(row.get("observed_order") or [])
        sources = "; ".join([x for x in (row.get("observed_sources") or []) if x])
        debug = row.get("graph_debug") or {}
        materialization = row.get("materialization_debug") or {}
        lines.extend(
            [
                f"[{i}]",
                f"Case : {row.get('case_id')}",
                f"Prioritization : {row.get('prioritization_mode')}",
                f"Expected order : {expected or '(none)'}",
                f"Observed order : {observed or '(none)'}",
                f"Observed sources : {sources or '(none)'}",
                f"Graph debug : {json.dumps(debug, ensure_ascii=False, sort_keys=True)}",
                f"Materialization debug : {json.dumps(materialization, ensure_ascii=False, sort_keys=True)}",
                "",
            ]
        )
    text = "\n".join(lines)
    detailed_path.write_text(text, encoding="utf-8")
    detailed_archived.write_text(text, encoding="utf-8")

    # Append to unified integration log (if present) for easy comparison.
    unified_log = out_dir / "test_results_latest.log"
    append_lines = [
        "",
        "=== Fetch Node Texts Results ===",
        "",
        f"Generated UTC: {generated_utc}",
        "",
    ] + lines[2:]
    if unified_log.exists():
        unified_log.write_text(unified_log.read_text(encoding="utf-8") + "\n" + "\n".join(append_lines), encoding="utf-8")
    else:
        unified_log.write_text("\n".join(append_lines), encoding="utf-8")


def test_fetch_node_texts_order_and_limits(retrieval_integration_env) -> None:
    seed_files = (
        "src/FakeEnterprise.Core/Search/SearchFacade.cs",
        "src/FakeEnterprise.Core/Retrieval/Hybrid/HybridRanker.cs",
        "src/FakeEnterprise.Core/Retrieval/Bm25/Bm25Searcher.cs",
    )
    graph_files = (
        "src/FakeEnterprise.Core/Retrieval/Bm25/KeywordExtractor.cs",
        "src/FakeEnterprise.Core/Retrieval/Semantic/SemanticSearcher.cs",
        "src/FakeEnterprise.Domain/Finance/PaymentService.cs",
    )
    atomic_skip_extra_files = (
        "src/FakeEnterprise.Core/Routing/QueryRouter.cs",
        "src/FakeEnterprise.Core/Routing/QueryParser.cs",
        "src/FakeEnterprise.Domain/Shipments/ShipmentService.cs",
    )

    client = _connect(retrieval_integration_env)
    try:
        snapshot_id = _resolve_primary_snapshot(retrieval_integration_env)
        seed_ids = _canonical_ids_for_sources(
            client=client,
            repository=retrieval_integration_env.repo_name,
            snapshot_id=snapshot_id,
            source_files=seed_files,
        )
        graph_ids = _canonical_ids_for_sources(
            client=client,
            repository=retrieval_integration_env.repo_name,
            snapshot_id=snapshot_id,
            source_files=graph_files,
        )
        extra_ids = _canonical_ids_for_sources(
            client=client,
            repository=retrieval_integration_env.repo_name,
            snapshot_id=snapshot_id,
            source_files=atomic_skip_extra_files,
        )
        all_ids = seed_ids + graph_ids + extra_ids
        source_map = _load_source_files(client, retrieval_integration_env.repo_name, snapshot_id, all_ids)
        backend = WeaviateRetrievalBackend(client=client)
        texts = backend.fetch_texts(
            node_ids=all_ids,
            repository=retrieval_integration_env.repo_name,
            snapshot_id=snapshot_id,
        )
    finally:
        client.close()

    assert seed_ids and graph_ids, "Missing seed or graph ids for fetch_node_texts tests."
    for nid in all_ids:
        assert texts.get(nid), f"Expected non-empty text for node: {source_map.get(nid, nid)}"

    token_counter = _TokenCounter()
    token_counts = _token_counts(token_counter, texts)

    graph_edges = [
        {"from_id": seed_ids[0], "to_id": graph_ids[0], "edge_type": "Calls"},
        {"from_id": seed_ids[0], "to_id": graph_ids[1], "edge_type": "Calls"},
        {"from_id": seed_ids[1], "to_id": graph_ids[2], "edge_type": "Calls"},
    ]
    depth_map, parent_map = _build_depth_parent(seed_ids, graph_edges)

    # F1 baseline
    state_f1 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=seed_ids[:2],
        graph_ids=[],
        graph_edges=[],
        budget_tokens=300,
        budget_tokens_from_settings=None,
        max_chars=None,
        prioritization_mode="seed_first",
    )
    observed_f1 = [str(item.get("id") or "") for item in (state_f1.node_texts or []) if isinstance(item, dict)]
    assert observed_f1 == seed_ids[:2]
    _append_fetch_report_row(case_id="F1", state=state_f1, expected_order=seed_ids[:2], source_map=source_map)

    # F2 seed_first (order, include all)
    budget_all = sum(token_counts.values()) + 50
    state_f2 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=seed_ids,
        graph_ids=graph_ids,
        graph_edges=graph_edges,
        budget_tokens=budget_all,
        budget_tokens_from_settings=None,
        max_chars=None,
        prioritization_mode="seed_first",
    )
    expected_f2 = _expected_seed_first_order(seed_ids, graph_ids, depth_map)
    observed_f2 = [str(item.get("id") or "") for item in (state_f2.node_texts or []) if isinstance(item, dict)]
    assert observed_f2 == expected_f2
    _append_fetch_report_row(case_id="F2", state=state_f2, expected_order=expected_f2, source_map=source_map)

    # F3 graph_first (order, include all)
    state_f3 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=seed_ids,
        graph_ids=graph_ids,
        graph_edges=graph_edges,
        budget_tokens=budget_all,
        budget_tokens_from_settings=None,
        max_chars=None,
        prioritization_mode="graph_first",
    )
    expected_f3 = _expected_graph_first_order(seed_ids, graph_ids, depth_map, parent_map)
    observed_f3 = [str(item.get("id") or "") for item in (state_f3.node_texts or []) if isinstance(item, dict)]
    assert observed_f3 == expected_f3
    _append_fetch_report_row(case_id="F3", state=state_f3, expected_order=expected_f3, source_map=source_map)

    # F4 balanced (order, include all)
    state_f4 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=seed_ids,
        graph_ids=graph_ids,
        graph_edges=graph_edges,
        budget_tokens=budget_all,
        budget_tokens_from_settings=None,
        max_chars=None,
        prioritization_mode="balanced",
    )
    expected_f4 = _expected_balanced_order(seed_ids, graph_ids, depth_map)
    observed_f4 = [str(item.get("id") or "") for item in (state_f4.node_texts or []) if isinstance(item, dict)]
    assert observed_f4 == expected_f4
    _append_fetch_report_row(case_id="F4", state=state_f4, expected_order=expected_f4, source_map=source_map)

    # F5 budget_tokens limit
    budget_limit = token_counts[seed_ids[0]] + token_counts[seed_ids[1]]
    state_f5 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=seed_ids,
        graph_ids=graph_ids[:2],
        graph_edges=graph_edges[:2],
        budget_tokens=budget_limit,
        budget_tokens_from_settings=None,
        max_chars=None,
        prioritization_mode="seed_first",
    )
    observed_f5 = [str(item.get("id") or "") for item in (state_f5.node_texts or []) if isinstance(item, dict)]
    assert observed_f5 == seed_ids[:2]
    assert int((state_f5.graph_debug or {}).get("used_tokens") or 0) <= budget_limit
    _append_fetch_report_row(case_id="F5", state=state_f5, expected_order=seed_ids[:2], source_map=source_map)

    # F6 budget_tokens_from_settings
    settings_budget = budget_all
    state_f6 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=seed_ids,
        graph_ids=graph_ids,
        graph_edges=graph_edges,
        budget_tokens=None,
        budget_tokens_from_settings="evidence_budget_tokens",
        max_chars=None,
        prioritization_mode="seed_first",
        settings_extra={"evidence_budget_tokens": settings_budget},
    )
    observed_f6 = [str(item.get("id") or "") for item in (state_f6.node_texts or []) if isinstance(item, dict)]
    assert observed_f6 == expected_f2
    assert int((state_f6.graph_debug or {}).get("budget_tokens") or 0) == settings_budget
    _append_fetch_report_row(case_id="F6", state=state_f6, expected_order=expected_f2, source_map=source_map)

    # F7 max_chars limit
    max_chars = len(texts[seed_ids[0]]) + len(texts[seed_ids[1]])
    state_f7 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=seed_ids,
        graph_ids=graph_ids[:2],
        graph_edges=graph_edges[:2],
        budget_tokens=None,
        budget_tokens_from_settings=None,
        max_chars=max_chars,
        prioritization_mode="seed_first",
    )
    observed_f7 = [str(item.get("id") or "") for item in (state_f7.node_texts or []) if isinstance(item, dict)]
    assert observed_f7 == seed_ids[:2]
    assert int((state_f7.graph_debug or {}).get("used_chars") or 0) <= max_chars
    _append_fetch_report_row(case_id="F7", state=state_f7, expected_order=seed_ids[:2], source_map=source_map)

    # F8 atomic skip (A included, B skipped, C included)
    a_id, b_id, c_id = _pick_atomic_skip_triplet(all_ids, token_counts)
    atomic_budget = token_counts[a_id] + token_counts[c_id]
    state_f8 = _run_fetch(
        env=retrieval_integration_env,
        seed_ids=[a_id, b_id, c_id],
        graph_ids=[],
        graph_edges=[],
        budget_tokens=atomic_budget,
        budget_tokens_from_settings=None,
        max_chars=None,
        prioritization_mode="seed_first",
    )
    observed_f8 = [str(item.get("id") or "") for item in (state_f8.node_texts or []) if isinstance(item, dict)]
    assert observed_f8 == [a_id, c_id]
    debug_budget = (getattr(state_f8, "_fetch_node_texts_debug", {}) or {}).get("budget", {}) or {}
    assert str(debug_budget.get("first_skipped_due_budget_id") or "") == b_id
    _append_fetch_report_row(case_id="F8", state=state_f8, expected_order=[a_id, c_id], source_map=source_map)
