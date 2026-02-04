from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os

import pytest
import weaviate

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.actions.search_nodes import SearchNodesAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend
from code_query_engine.pipeline.state import PipelineState
from server.snapshots.snapshot_registry import SnapshotRegistry


@dataclass(frozen=True)
class QueryCase:
    search_type: str
    query: str
    expected_markers: tuple[str, ...]
    snapshot_source: str = "primary"
    assumption_id: str = ""
    expected_hits: tuple[str, ...] = ()


_CASES: list[QueryCase] = [
    # semantic (5)
    QueryCase(
        "semantic",
        "Where is the application entry point and bootstrap?",
        ("point, entry point", "bootstrap"),
        assumption_id="1.1",
        expected_hits=("Program.cs", "AppBootstrap.cs", "QueryRouter.cs"),
    ),
    QueryCase(
        "semantic",
        "How does semantic search and nearest neighbors work?",
        ("semantic search", "nearest neighbors"),
        assumption_id="1.2",
        expected_hits=("SemanticSearcher.cs", "EmbeddingModel.cs", "NearestNeighbors.cs", "CosineSimilarity.cs"),
    ),
    QueryCase(
        "semantic",
        "Which component combines BM25 and semantic search?",
        ("bm25", "semantic", "hybrid"),
        assumption_id="1.3",
        expected_hits=("HybridRanker.cs", "ReciprocalRankFusion.cs", "KeywordRerankScorer.cs", "SearchFacade.cs"),
    ),
    QueryCase(
        "semantic",
        "Where is fraud risk calculated with token validation?",
        ("fraud, risk score", "token validation"),
        assumption_id="1.4",
        expected_hits=("FraudRiskScorer.cs", "TokenValidator.cs", "proc_ComputeFraudRisk.sql"),
    ),
    QueryCase(
        "semantic",
        "How do we search shipments by tracking number?",
        ("tracking number", "shipment"),
        assumption_id="1.5",
        expected_hits=("ShipmentService.cs", "ShipmentRepository.cs", "proc_GetShipmentByTracking.sql", "view_Shipments.sql"),
    ),
    # bm25 (5)
    QueryCase("bm25", "proc_SearchShipments_BM25", ("proc_SearchShipments_BM25",), assumption_id="2.1", expected_hits=("proc_SearchShipments_BM25.sql",)),
    QueryCase("bm25", "KeywordExtractor ExtractKeywords", ("ExtractKeywords",), assumption_id="2.2", expected_hits=("KeywordExtractor.cs", "Bm25Searcher.cs")),
    QueryCase("bm25", "TokenValidator ValidateToken", ("ValidateToken", "signature verification"), assumption_id="2.3", expected_hits=("TokenValidator.cs", "proc_ValidateToken.sql")),
    QueryCase(
        "bm25",
        "table_Payments proc_ProcessPayment",
        ("table_Payments", "proc_ProcessPayment", "PaymentService", "proc_GenerateInvoice"),
        assumption_id="2.4",
        expected_hits=(
            "table_Payments.sql",
            "proc_ProcessPayment.sql",
            "PaymentService.cs",
            "proc_GenerateInvoice.sql",
        ),
    ),
    QueryCase("bm25", "DependencyTreeExpander", ("DependencyTreeExpander",), assumption_id="2.5", expected_hits=("DependencyTreeExpander.cs", "GraphProviderFacade.cs")),
    # hybrid (5)
    QueryCase("hybrid", "hybrid search BM25 semantic rerank shipments", ("hybrid", "bm25", "semantic"), assumption_id="3.1", expected_hits=("HybridRanker.cs", "SearchFacade.cs", "proc_SearchShipments_Hybrid.sql")),
    QueryCase("hybrid", "ACL filter before rank", ("acl", "filter", "permissions"), assumption_id="3.2", expected_hits=("AclFilter.cs", "AclPolicy.cs", "SearchFacade.cs")),
    QueryCase("hybrid", "payments invoices VAT", ("payment", "invoice", "vat"), assumption_id="3.3", expected_hits=("PaymentService.cs", "InvoiceGenerator.cs", "VatCalculator.cs", "table_Payments.sql")),
    QueryCase("hybrid", "who calls stored procedure execute", ("stored procedure", "SqlExecutor"), assumption_id="3.4", expected_hits=("SqlExecutor.cs", "ShipmentService.cs", "PaymentService.cs")),
    QueryCase("hybrid", "query routing and retrieval strategy selection", ("route request", "search facade"), assumption_id="3.5", expected_hits=("QueryRouter.cs", "QueryParser.cs", "SearchFacade.cs")),
]

_REPORT_ROWS: list[dict[str, Any]] = []
_PIPELINE_TRACE_DIR = Path("log") / "integration" / "retrival" / "pipeline_traces"


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


def _run_search_and_fetch(*, env, case: QueryCase, retrieval_filters_override: dict[str, Any] | None = None) -> PipelineState:
    client = _connect(env)
    try:
        embed_model = os.getenv("INTEGRATION_EMBED_MODEL", "models/embedding/e5-base-v2").strip()
        backend = WeaviateRetrievalBackend(client=client, query_embed_model=embed_model)
        registry = SnapshotRegistry(client)
        snapshots = registry.list_snapshots(snapshot_set_id=env.snapshot_set_id, repository=env.repo_name)
        assert snapshots, "SnapshotSet does not contain snapshots."

        primary = snapshots[0].id
        secondary = snapshots[1].id if len(snapshots) > 1 else None

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
        if retrieval_filters_override:
            state.retrieval_filters = dict(retrieval_filters_override)

        runtime = PipelineRuntime(
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
            retrieval_backend=backend,
            graph_provider=None,
            token_counter=_TokenCounter(),
            add_plant_link=lambda x, _consultant=None: x,
        )
        setattr(runtime, "pipeline_trace_enabled", True)
        setattr(state, "pipeline_trace_events", [])

        search_step = StepDef(
            id="search",
            action="search_nodes",
            raw={
                "id": "search",
                "action": "search_nodes",
                "search_type": case.search_type,
                "top_k": 8,
                **({"snapshot_source": "secondary"} if case.snapshot_source == "secondary" else {}),
            },
        )
        SearchNodesAction().execute(search_step, state, runtime)

        fetch_step = StepDef(
            id="fetch",
            action="fetch_node_texts",
            raw={
                "id": "fetch",
                "action": "fetch_node_texts",
                "budget_tokens": 6000,
                "prioritization_mode": "seed_first",
            },
        )
        FetchNodeTextsAction().execute(fetch_step, state, runtime)
        _write_pipeline_trace(case=case, state=state)

        return state
    finally:
        client.close()


def _first_text_preview(state: PipelineState, limit: int = 220) -> str:
    for item in (state.node_texts or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            return text[:limit].replace("\n", " ")
    return ""


def _load_observed_sources(client: weaviate.WeaviateClient, state: PipelineState, repo: str) -> list[str]:
    try:
        from weaviate.classes.query import Filter
    except Exception:
        return []

    snapshot_id = str((state.retrieval_filters or {}).get("snapshot_id") or state.snapshot_id or "").strip()
    node_ids = list(state.retrieval_seed_nodes or [])
    if not snapshot_id or not node_ids:
        return []

    coll = client.collections.use("RagNode")
    filt = (
        Filter.by_property("repo").equal(repo)
        & Filter.by_property("snapshot_id").equal(snapshot_id)
        & Filter.by_property("canonical_id").contains_any(node_ids)
    )
    res = coll.query.fetch_objects(
        filters=filt,
        limit=max(len(node_ids), 8),
        return_properties=["canonical_id", "source_file", "sql_name", "class_name", "member_name"],
    )
    out: list[str] = []
    for obj in (res.objects or []):
        p = obj.properties or {}
        src = str(p.get("source_file") or "").strip()
        if src:
            out.append(src)
            continue
        class_name = str(p.get("class_name") or "").strip()
        member_name = str(p.get("member_name") or "").strip()
        sql_name = str(p.get("sql_name") or "").strip()
        fallback = " ".join([x for x in (class_name, member_name, sql_name) if x]).strip()
        if fallback:
            out.append(fallback)
    # stable, unique
    seen = set()
    uniq = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def _load_observed_docs(client: weaviate.WeaviateClient, state: PipelineState, repo: str) -> list[dict[str, Any]]:
    try:
        from weaviate.classes.query import Filter
    except Exception:
        return []

    snapshot_id = str((state.retrieval_filters or {}).get("snapshot_id") or state.snapshot_id or "").strip()
    node_ids = list(state.retrieval_seed_nodes or [])
    if not snapshot_id or not node_ids:
        return []

    coll = client.collections.use("RagNode")
    filt = (
        Filter.by_property("repo").equal(repo)
        & Filter.by_property("snapshot_id").equal(snapshot_id)
        & Filter.by_property("canonical_id").contains_any(node_ids)
    )
    res = coll.query.fetch_objects(
        filters=filt,
        limit=max(len(node_ids), 8),
        return_properties=["canonical_id", "source_file", "acl_allow", "classification_labels"],
    )
    out: list[dict[str, Any]] = []
    for obj in (res.objects or []):
        p = obj.properties or {}
        out.append(
            {
                "canonical_id": str(p.get("canonical_id") or "").strip(),
                "source_file": str(p.get("source_file") or "").strip(),
                "acl_allow": [str(x).strip() for x in (p.get("acl_allow") or []) if str(x).strip()],
                "classification_labels": [str(x).strip() for x in (p.get("classification_labels") or []) if str(x).strip()],
            }
        )
    return out


def _append_report_row(*, test_id: str, case: QueryCase, state: PipelineState) -> None:
    combined = "\n".join(str(item.get("text") or "").lower() for item in state.node_texts if isinstance(item, dict))
    matched = [m for m in case.expected_markers if m.lower() in combined]
    _REPORT_ROWS.append(
        {
            "test_id": test_id,
            "search_type": case.search_type,
            "snapshot_source": case.snapshot_source,
            "query": case.query,
            "expected_markers": list(case.expected_markers),
            "matched_markers": matched,
            "matched_any": bool(matched),
            "seed_count": len(state.retrieval_seed_nodes or []),
            "node_texts_count": len(state.node_texts or []),
            "first_seed_node": (state.retrieval_seed_nodes[0] if state.retrieval_seed_nodes else ""),
            "first_text_preview": _first_text_preview(state),
            "assumption_id": case.assumption_id,
            "expected_hits": list(case.expected_hits),
            "observed_sources": list(getattr(state, "_observed_sources", []) or []),
            "observed_docs": list(getattr(state, "_observed_docs", []) or []),
            "retrieval_filters": dict(getattr(state, "retrieval_filters", {}) or {}),
        }
    )


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, set):
        return sorted([_jsonable(x) for x in obj], key=lambda x: str(x))
    return repr(obj)


def _slug(value: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in (value or ""))
    clean = "_".join([x for x in clean.split("_") if x])
    return clean[:72] if clean else "case"


def _write_pipeline_trace(*, case: QueryCase, state: PipelineState) -> None:
    _PIPELINE_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    ts_safe = ts.strftime("%Y-%m-%dT%H-%M-%SZ")
    file_name = f"{ts_safe}_{_slug(case.search_type)}_{_slug(case.query)}.json"
    payload = {
        "generated_utc": ts.isoformat(timespec="seconds"),
        "query": case.query,
        "search_mode": case.search_type,
        "snapshot_source": case.snapshot_source,
        "assumption_id": case.assumption_id,
        "state_after": _jsonable(getattr(state, "__dict__", {})),
        "events": _jsonable(getattr(state, "pipeline_trace_events", []) or []),
    }

    path = _PIPELINE_TRACE_DIR / file_name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = _PIPELINE_TRACE_DIR / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def _write_expectations_report() -> None:
    yield
    if not _REPORT_ROWS:
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = Path("log") / "integration" / "retrival"
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    simple_log_path = out_dir / "test_results_latest.log"
    simple_archived_log = out_dir / f"test_results_{ts}.log"
    # Cleanup old Polish-named logs if they exist from previous runs.
    for old in out_dir.glob("wyniki_testow*.log"):
        try:
            old.unlink()
        except Exception:
            pass
    simple_lines: list[str] = [
        f"Generated UTC: {generated_utc}",
        "",
    ]
    for i, row in enumerate(_REPORT_ROWS, start=1):
        observed = row.get("observed_sources") or []
        if not observed:
            observed = row.get("matched_markers") or []
        observed_text = "; ".join(str(x) for x in observed) if observed else "(none)"
        observed_docs = row.get("observed_docs") or []
        security_text = "(none)"
        if observed_docs:
            entries: list[str] = []
            for doc in observed_docs:
                source = str(doc.get("source_file") or "")
                acl = ",".join(str(x) for x in (doc.get("acl_allow") or []))
                labels = ",".join(str(x) for x in (doc.get("classification_labels") or []))
                entries.append(f"{source} [acl={acl or '-'} | cls={labels or '-'}]")
            security_text = "; ".join(entries)
        filters_text = json.dumps(row.get("retrieval_filters") or {}, ensure_ascii=False, sort_keys=True)
        simple_lines.extend(
            [
                f"[{i}]",
                f"Question : {row.get('query')}",
                f"Search mode : {row.get('search_type')}",
                f"Applied filters : {filters_text}",
                f"Observed results : {observed_text}",
                f"Observed security : {security_text}",
                "",
            ]
        )
    simple_text = "\n".join(simple_lines)
    simple_log_path.write_text(simple_text, encoding="utf-8")
    simple_archived_log.write_text(simple_text, encoding="utf-8")


@pytest.mark.parametrize("case", _CASES, ids=[f"{c.search_type}:{i+1}" for i, c in enumerate(_CASES)])
def test_search_then_fetch_matches_expected_markers(retrieval_integration_env, case: QueryCase) -> None:
    state = _run_search_and_fetch(env=retrieval_integration_env, case=case)
    client = _connect(retrieval_integration_env)
    try:
        setattr(state, "_observed_sources", _load_observed_sources(client, state, retrieval_integration_env.repo_name))
        setattr(state, "_observed_docs", _load_observed_docs(client, state, retrieval_integration_env.repo_name))
    finally:
        client.close()
    _append_report_row(
        test_id=f"{case.search_type}:{case.query}",
        case=case,
        state=state,
    )

    assert state.retrieval_seed_nodes, "search_nodes returned no seed nodes."
    assert state.node_texts, "fetch_node_texts returned no texts."

    combined = "\n".join(str(item.get("text") or "").lower() for item in state.node_texts if isinstance(item, dict))
    assert combined.strip(), "All fetched texts are empty."
    marker_hit = any(marker.lower() in combined for marker in case.expected_markers)
    observed_sources = list(getattr(state, "_observed_sources", []) or [])
    expected_hit_present = any(
        expected.lower() in source.lower()
        for expected in case.expected_hits
        for source in observed_sources
    )
    assert marker_hit or expected_hit_present, (
        f"Expected marker {case.expected_markers} or expected source {case.expected_hits} "
        f"for query={case.query!r}. Observed sources={observed_sources}"
    )


def test_search_then_fetch_secondary_snapshot_source_works(retrieval_integration_env) -> None:
    case = QueryCase(
        search_type="semantic",
        query="token validation and auth",
        expected_markers=("token validation", "jwt"),
        snapshot_source="secondary",
    )
    state = _run_search_and_fetch(env=retrieval_integration_env, case=case)
    client = _connect(retrieval_integration_env)
    try:
        setattr(state, "_observed_sources", _load_observed_sources(client, state, retrieval_integration_env.repo_name))
        setattr(state, "_observed_docs", _load_observed_docs(client, state, retrieval_integration_env.repo_name))
    finally:
        client.close()
    _append_report_row(
        test_id=f"secondary:{case.query}",
        case=case,
        state=state,
    )

    assert state.retrieval_seed_nodes
    combined = "\n".join(str(item.get("text") or "").lower() for item in state.node_texts if isinstance(item, dict))
    assert "token" in combined


def _assert_docs_respect_filters(docs: list[dict[str, Any]], filters: dict[str, Any]) -> None:
    acl_any = [str(x).strip() for x in (filters.get("acl_tags_any") or []) if str(x).strip()]
    cls_all = [str(x).strip() for x in (filters.get("classification_labels_all") or []) if str(x).strip()]
    for doc in docs:
        doc_acl = [str(x).strip() for x in (doc.get("acl_allow") or []) if str(x).strip()]
        doc_cls = [str(x).strip() for x in (doc.get("classification_labels") or []) if str(x).strip()]
        if acl_any:
            assert set(doc_acl).intersection(acl_any), (
                f"ACL filter mismatch. expected any={acl_any}, got doc_acl={doc_acl}, source={doc.get('source_file')}"
            )
        if cls_all:
            assert set(cls_all).issubset(set(doc_cls)), (
                f"Classification filter mismatch. expected all={cls_all}, got doc_cls={doc_cls}, source={doc.get('source_file')}"
            )


def _run_and_assert_security_case(
    *,
    retrieval_integration_env,
    test_id: str,
    filters: dict[str, Any],
    assumption_id: str,
) -> None:
    case = QueryCase(
        search_type="bm25",
        query="deterministic searchable content integration tests",
        expected_markers=("integration tests",),
        snapshot_source="primary",
        assumption_id=assumption_id,
    )
    state = _run_search_and_fetch(
        env=retrieval_integration_env,
        case=case,
        retrieval_filters_override=filters,
    )
    client = _connect(retrieval_integration_env)
    try:
        observed_sources = _load_observed_sources(client, state, retrieval_integration_env.repo_name)
        observed_docs = _load_observed_docs(client, state, retrieval_integration_env.repo_name)
        setattr(state, "_observed_sources", observed_sources)
        setattr(state, "_observed_docs", observed_docs)
    finally:
        client.close()

    _append_report_row(test_id=test_id, case=case, state=state)

    assert state.retrieval_seed_nodes, f"{test_id}: search_nodes returned no seed nodes."
    assert observed_docs, f"{test_id}: no observed docs for filter validation."
    applied = dict(getattr(state, "retrieval_filters", {}) or {})
    for key in ("repo", "snapshot_id"):
        assert key in applied and str(applied.get(key) or "").strip(), f"{test_id}: missing required filter key={key!r}"
    for key in ("acl_tags_any", "classification_labels_all"):
        if key in filters:
            assert applied.get(key), f"{test_id}: expected filter key={key!r} to be present in applied filters."

    _assert_docs_respect_filters(observed_docs, filters)


def test_security_acl_any_filter_is_applied(retrieval_integration_env) -> None:
    _run_and_assert_security_case(
        retrieval_integration_env=retrieval_integration_env,
        test_id="security:acl_any",
        filters={"acl_tags_any": ["finance", "security"]},
        assumption_id="5.acl_any",
    )


def test_security_classification_all_filter_is_applied(retrieval_integration_env) -> None:
    _run_and_assert_security_case(
        retrieval_integration_env=retrieval_integration_env,
        test_id="security:classification_all",
        filters={"classification_labels_all": ["restricted"]},
        assumption_id="5.classification_all",
    )


def test_security_acl_and_classification_filters_are_applied_together(retrieval_integration_env) -> None:
    _run_and_assert_security_case(
        retrieval_integration_env=retrieval_integration_env,
        test_id="security:acl_and_classification",
        filters={
            "acl_tags_any": ["finance", "security"],
            "classification_labels_all": ["restricted"],
        },
        assumption_id="5.acl_and_classification",
    )
