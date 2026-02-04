#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


ACL_TAGS = [
    "finance",
    "security",
    "ops",
    "hr",
    "legal",
    "architecture",
    "integration",
    "support",
]

CLASSIFICATION_LABELS = [
    "public",
    "internal",
    "restricted",
    "confidential",
    "secret",
]

OWNER_IDS = [
    "team-finance",
    "team-security",
    "team-platform",
    "team-integration",
]


@dataclass
class CsNode:
    key: str
    file: str
    class_name: str
    member: str
    text: str
    deps: List[str]
    obj: Dict[str, object]


@dataclass
class SqlNode:
    key: str
    kind: str
    schema: str
    name: str
    file: str
    body: str
    obj: Dict[str, object]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head_sha(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _base_cs_nodes(release: str) -> List[Tuple[str, str, str, str, str]]:
    version_suffix = "1.1 improvements with intent classification and stronger governance." if release == "1.1" else "1.0 baseline implementation."
    return [
        ("program", "src/FakeEnterprise.App/Program.cs", "Program", "Main", f"Application entry point and bootstrap root. {version_suffix}"),
        ("bootstrap", "src/FakeEnterprise.App/AppBootstrap.cs", "AppBootstrap", "Configure", "Registers services, repositories, routing and telemetry."),
        ("router", "src/FakeEnterprise.Core/Routing/QueryRouter.cs", "QueryRouter", "RouteRequest", "Routes user questions to retrieval strategies based on intent."),
        ("parser", "src/FakeEnterprise.Core/Routing/QueryParser.cs", "QueryParser", "Parse", "Parses query text, filters and optional retrieval hints."),
        ("facade", "src/FakeEnterprise.Core/Search/SearchFacade.cs", "SearchFacade", "Search", "Combines semantic, BM25 and graph expansion for final evidence."),
        ("semantic_searcher", "src/FakeEnterprise.Core/Retrieval/Semantic/SemanticSearcher.cs", "SemanticSearcher", "Search", "Runs vector search using nearest neighbors."),
        ("embed_model", "src/FakeEnterprise.Core/Retrieval/Semantic/EmbeddingModel.cs", "EmbeddingModel", "Encode", "Encodes text to embedding vectors with normalization."),
        ("nearest", "src/FakeEnterprise.Core/Retrieval/Semantic/NearestNeighbors.cs", "NearestNeighbors", "FindTopK", "Finds nearest vectors using cosine distance."),
        ("cosine", "src/FakeEnterprise.Core/Retrieval/Semantic/CosineSimilarity.cs", "CosineSimilarity", "Score", "Computes cosine similarity for ranking."),
        ("embed_query", "src/FakeEnterprise.Core/Retrieval/Semantic/EmbeddingQueryBuilder.cs", "EmbeddingQueryBuilder", "Build", "Builds normalized embedding query payloads."),
        ("bm25_searcher", "src/FakeEnterprise.Core/Retrieval/Bm25/Bm25Searcher.cs", "Bm25Searcher", "Search", "Performs lexical BM25 retrieval with exact-token boost."),
        ("bm25_scorer", "src/FakeEnterprise.Core/Retrieval/Bm25/Bm25Scorer.cs", "Bm25Scorer", "Score", "Calculates BM25 scores and field boosts."),
        ("keyword_extractor", "src/FakeEnterprise.Core/Retrieval/Bm25/KeywordExtractor.cs", "KeywordExtractor", "ExtractKeywords", "Extracts hard keywords for lexical search."),
        ("tokenizer", "src/FakeEnterprise.Core/Retrieval/Bm25/TfTokenizer.cs", "TfTokenizer", "Tokenize", "Tokenizes source terms for TF and BM25 features."),
        ("stopwords", "src/FakeEnterprise.Core/Retrieval/Bm25/StopwordList.cs", "StopwordList", "Contains", "Maintains stopword list for lexical normalization."),
        ("hybrid_ranker", "src/FakeEnterprise.Core/Retrieval/Hybrid/HybridRanker.cs", "HybridRanker", "Rank", "Merges semantic and BM25 hits using hybrid rank fusion."),
        ("rrf", "src/FakeEnterprise.Core/Retrieval/Hybrid/ReciprocalRankFusion.cs", "ReciprocalRankFusion", "Fuse", "Implements reciprocal rank fusion scoring."),
        ("keyword_rerank", "src/FakeEnterprise.Core/Retrieval/Hybrid/KeywordRerankScorer.cs", "KeywordRerankScorer", "Rerank", "Reranks semantic hits with strong keyword evidence."),
        ("dep_tree", "src/FakeEnterprise.Core/Graph/DependencyTreeExpander.cs", "DependencyTreeExpander", "Expand", "Expands dependency graph from retrieval seed nodes."),
        ("graph_facade", "src/FakeEnterprise.Core/Graph/GraphProviderFacade.cs", "GraphProviderFacade", "ExpandTree", "Facade over graph provider and graph filters."),
        ("token_validator", "src/FakeEnterprise.Domain/Security/TokenValidator.cs", "TokenValidator", "ValidateToken", "Performs token validation and signature verification."),
        ("acl_filter", "src/FakeEnterprise.Core/Security/AclFilter.cs", "AclFilter", "Apply", "Applies ACL filters before ranking and context materialization."),
        ("acl_policy", "src/FakeEnterprise.Core/Security/AclPolicy.cs", "AclPolicy", "CanRead", "Evaluates access tags and classification labels."),
        ("fraud_scorer", "src/FakeEnterprise.Domain/Risk/FraudRiskScorer.cs", "FraudRiskScorer", "ComputeScore", "Computes fraud risk score with security checks."),
        ("shipment_service", "src/FakeEnterprise.Domain/Shipments/ShipmentService.cs", "ShipmentService", "SearchByTracking", "Searches shipments by tracking number and customer scope."),
        ("shipment_repo", "src/FakeEnterprise.Domain/Shipments/ShipmentRepository.cs", "ShipmentRepository", "FindByTracking", "Loads shipment rows from SQL layer."),
        ("payment_service", "src/FakeEnterprise.Domain/Finance/PaymentService.cs", "PaymentService", "ProcessPayment", "Processes payments with anti-fraud checks."),
        ("invoice_generator", "src/FakeEnterprise.Domain/Finance/InvoiceGenerator.cs", "InvoiceGenerator", "GenerateInvoice", "Generates invoice documents and VAT summaries."),
        ("vat_calculator", "src/FakeEnterprise.Domain/Finance/VatCalculator.cs", "VatCalculator", "CalculateVat", "Calculates VAT amount and taxable totals."),
        ("sql_executor", "src/FakeEnterprise.Infrastructure/Db/SqlExecutor.cs", "SqlExecutor", "ExecuteStoredProcedure", "Executes stored procedures with retry and telemetry."),
        ("db_factory", "src/FakeEnterprise.Infrastructure/Db/DbConnectionFactory.cs", "DbConnectionFactory", "Create", "Creates resilient database connections."),
    ]


def _base_cs_edges() -> Dict[str, List[str]]:
    return {
        "program": ["bootstrap"],
        "bootstrap": ["router", "facade", "db_factory"],
        "router": ["parser", "facade"],
        "facade": ["semantic_searcher", "bm25_searcher", "hybrid_ranker", "dep_tree"],
        "semantic_searcher": ["embed_model", "nearest", "cosine", "embed_query"],
        "bm25_searcher": ["bm25_scorer", "keyword_extractor", "tokenizer", "stopwords"],
        "hybrid_ranker": ["rrf", "keyword_rerank"],
        "dep_tree": ["graph_facade"],
        "shipment_service": ["shipment_repo", "sql_executor"],
        "payment_service": ["sql_executor", "fraud_scorer", "vat_calculator"],
        "invoice_generator": ["vat_calculator", "sql_executor"],
        "token_validator": ["acl_policy"],
        "acl_filter": ["acl_policy"],
        "fraud_scorer": ["token_validator"],
        "shipment_repo": ["sql_executor"],
    }


def _extra_cs_nodes(count: int, rng: random.Random) -> List[Tuple[str, str, str, str, str]]:
    out: List[Tuple[str, str, str, str, str]] = []
    domains = ["Diagnostics", "Parsing", "Utils", "Config", "Telemetry", "Caching", "Http", "IO", "Math", "Text"]
    topics = [
        "request correlation",
        "cache hydration",
        "input normalization",
        "error mapping",
        "retry policy",
        "pagination helper",
        "query preparation",
        "result projection",
        "domain validation",
        "integration telemetry",
    ]
    for i in range(1, count + 1):
        domain = domains[(i - 1) % len(domains)]
        topic = topics[(i - 1) % len(topics)]
        key = f"extra_{i:03d}"
        cls = f"{domain}C{i:04d}"
        file = f"src/FakeEnterprise.Core/{domain}/{cls}.cs"
        text = (
            f"Utility component for {topic}. "
            "This fake module provides deterministic searchable content for integration tests."
        )
        out.append((key, file, cls, "Run", text))
    rng.shuffle(out)
    return out


def _build_cs_release(release: str, rng: random.Random) -> Tuple[List[CsNode], Dict[str, List[str]]]:
    base = _base_cs_nodes(release)
    extras = _extra_cs_nodes(170, rng)
    items = base + extras

    if release == "1.1":
        items.append(
            (
                "intent_classifier",
                "src/FakeEnterprise.Core/Routing/QueryIntentClassifier.cs",
                "QueryIntentClassifier",
                "Classify",
                "Classifies query intent and retrieval scope for improved routing decisions.",
            )
        )
        items.append(
            (
                "compliance_gateway",
                "src/FakeEnterprise.Core/Security/ComplianceGateway.cs",
                "ComplianceGateway",
                "ValidateRequest",
                "Validates compliance labels before sensitive evidence is returned.",
            )
        )

    nodes: List[CsNode] = []
    key_to_id: Dict[str, str] = {}
    for idx, (key, file, cls, member, text) in enumerate(items, start=1):
        cid = f"C{idx:04d}"
        key_to_id[key] = cid
        payload = {
            "Id": cid,
            "File": file,
            "RepoRelativePath": file,
            "ProjectName": "FakeEnterprise",
            "Class": cls,
            "Member": member,
            "Type": "Method",
            "ChunkPart": 1,
            "ChunkTotal": 1,
            "Text": (
                f"// FakeEnterprise release {release}\n"
                f"// Component: {cls}.{member}\n"
                f"// Keywords: {text}\n"
                "namespace FakeEnterprise;\n"
                f"public static class {cls} {{ public static void {member}() {{ }} }}\n"
            ),
            "acl_tags_any": [],
            "classification_labels_all": [],
            "owner_id": "",
            "source_system_id": "code.csharp",
        }
        nodes.append(CsNode(key=key, file=file, class_name=cls, member=member, text=text, deps=[], obj=payload))

    deps_by_key = _base_cs_edges()
    if release == "1.1":
        deps_by_key["router"] = deps_by_key.get("router", []) + ["intent_classifier"]
        deps_by_key["hybrid_ranker"] = deps_by_key.get("hybrid_ranker", []) + ["intent_classifier"]
        deps_by_key["token_validator"] = deps_by_key.get("token_validator", []) + ["compliance_gateway"]
        deps_by_key["acl_filter"] = deps_by_key.get("acl_filter", []) + ["compliance_gateway"]

    # Add lightweight chain dependencies for extras to keep graph connected.
    extra_keys = [n.key for n in nodes if n.key.startswith("extra_")]
    for i, key in enumerate(extra_keys):
        deps = deps_by_key.setdefault(key, [])
        if i > 0:
            deps.append(extra_keys[i - 1])
        if i > 2 and i % 4 == 0:
            deps.append(extra_keys[i - 3])
        if i % 7 == 0:
            deps.append("facade")

    # Convert key dependencies to id dependencies.
    dep_map: Dict[str, List[str]] = {}
    for node in nodes:
        key_deps = deps_by_key.get(node.key, [])
        id_deps = [key_to_id[k] for k in key_deps if k in key_to_id]
        dep_map[node.obj["Id"]] = sorted(set(id_deps))
        node.deps = dep_map[node.obj["Id"]]

    return nodes, dep_map


def _build_sql_release(release: str, rng: random.Random) -> Tuple[List[SqlNode], List[Dict[str, str]], List[Dict[str, str]]]:
    core_specs = [
        ("table_shipments", "TABLE", "dbo", "table_Shipments", "db/tables/table_Shipments.sql", "Table with shipment headers and tracking number."),
        ("table_payments", "TABLE", "dbo", "table_Payments", "db/tables/table_Payments.sql", "Table with payment transactions and statuses."),
        ("table_invoices", "TABLE", "dbo", "table_Invoices", "db/tables/table_Invoices.sql", "Table with invoice data and VAT amounts."),
        ("table_tokens", "TABLE", "dbo", "table_Tokens", "db/tables/table_Tokens.sql", "Table with token signatures and expiration windows."),
        ("table_acl", "TABLE", "dbo", "table_AclRecords", "db/tables/table_AclRecords.sql", "Table with ACL tag assignments per canonical id."),
        ("view_shipments", "VIEW", "dbo", "view_Shipments", "db/views/view_Shipments.sql", "View projecting shipment search fields."),
        ("view_finance", "VIEW", "dbo", "view_FinanceOverview", "db/views/view_FinanceOverview.sql", "View combining payments and invoices."),
        ("func_normalize", "FUNC", "dbo", "fn_NormalizeQuery", "db/func/fn_NormalizeQuery.sql", "Function normalizing lexical query text."),
        ("proc_bm25", "PROC", "dbo", "proc_SearchShipments_BM25", "db/procs/proc_SearchShipments_BM25.sql", "Procedure executing BM25 shipment search."),
        ("proc_semantic", "PROC", "dbo", "proc_SearchShipments_Semantic", "db/procs/proc_SearchShipments_Semantic.sql", "Procedure executing semantic shipment search."),
        ("proc_hybrid", "PROC", "dbo", "proc_SearchShipments_Hybrid", "db/procs/proc_SearchShipments_Hybrid.sql", "Procedure fusing semantic and BM25 search results."),
        ("proc_tracking", "PROC", "dbo", "proc_GetShipmentByTracking", "db/procs/proc_GetShipmentByTracking.sql", "Procedure retrieving shipment by tracking number."),
        ("proc_payment", "PROC", "dbo", "proc_ProcessPayment", "db/procs/proc_ProcessPayment.sql", "Procedure processing payment with anti-fraud verification."),
        ("proc_invoice", "PROC", "dbo", "proc_GenerateInvoice", "db/procs/proc_GenerateInvoice.sql", "Procedure generating invoice from payment records."),
        ("proc_validate_token", "PROC", "dbo", "proc_ValidateToken", "db/procs/proc_ValidateToken.sql", "Procedure validating token signature and scope."),
        ("proc_fraud", "PROC", "dbo", "proc_ComputeFraudRisk", "db/procs/proc_ComputeFraudRisk.sql", "Procedure computing fraud risk score."),
    ]

    if release == "1.1":
        core_specs += [
            ("table_audit", "TABLE", "dbo", "table_SearchAudit", "db/tables/table_SearchAudit.sql", "Table storing search audit events and classifier output."),
            ("proc_vector_fallback", "PROC", "dbo", "proc_SearchShipments_VectorFallback", "db/procs/proc_SearchShipments_VectorFallback.sql", "Procedure fallback when vector ranking is unavailable."),
        ]

    # Add SQL noise nodes (still English and coherent).
    for i in range(1, 75):
        core_specs.append(
            (
                f"extra_sql_{i:03d}",
                "PROC" if i % 3 == 0 else "TABLE",
                "dbo",
                f"proc_Extra_{i:03d}" if i % 3 == 0 else f"table_Extra_{i:03d}",
                f"db/extra/{'proc' if i % 3 == 0 else 'table'}_{i:03d}.sql",
                f"Supplementary fake SQL node {i} for integration retrieval realism.",
            )
        )

    nodes: List[SqlNode] = []
    for key, kind, schema, name, file, desc in core_specs:
        if kind == "TABLE":
            body = (
                f"-- FakeEnterprise release {release}\n"
                f"-- {desc}\n"
                f"CREATE TABLE [{schema}].[{name}] (Id INT PRIMARY KEY, Value NVARCHAR(200));\n"
            )
        elif kind == "VIEW":
            body = (
                f"-- FakeEnterprise release {release}\n"
                f"-- {desc}\n"
                f"CREATE VIEW [{schema}].[{name}] AS SELECT Id, Value FROM [{schema}].[table_Shipments];\n"
            )
        elif kind == "FUNC":
            body = (
                f"-- FakeEnterprise release {release}\n"
                f"-- {desc}\n"
                f"CREATE FUNCTION [{schema}].[{name}] (@q NVARCHAR(200)) RETURNS NVARCHAR(200) AS BEGIN RETURN LOWER(@q); END;\n"
            )
        else:
            body = (
                f"-- FakeEnterprise release {release}\n"
                f"-- {desc}\n"
                f"CREATE PROCEDURE [{schema}].[{name}] AS BEGIN SELECT 1 AS Result; END;\n"
            )
        obj = {
            "key": f"SQL:{schema}.{name}",
            "kind": {"PROC": "Procedure", "TABLE": "Table", "VIEW": "View", "FUNC": "Function"}.get(kind, kind),
            "schema": schema,
            "name": name,
            "file": file,
            "body": body,
            "data_type": "sql_code",
            "file_type": "sql",
            "domain": "sql",
            "acl_tags_any": [],
            "classification_labels_all": [],
            "owner_id": "",
            "source_system_id": "code.sql",
        }
        nodes.append(SqlNode(key=key, kind=kind, schema=schema, name=name, file=file, body=body, obj=obj))

    key_to_node = {n.key: n for n in nodes}
    edges: List[Tuple[str, str, str]] = [
        ("proc_tracking", "view_shipments", "ReadsFrom"),
        ("proc_bm25", "view_shipments", "ReadsFrom"),
        ("proc_semantic", "view_shipments", "ReadsFrom"),
        ("proc_hybrid", "proc_bm25", "Executes"),
        ("proc_hybrid", "proc_semantic", "Executes"),
        ("proc_payment", "table_payments", "WritesTo"),
        ("proc_payment", "proc_validate_token", "Executes"),
        ("proc_payment", "proc_fraud", "Executes"),
        ("proc_invoice", "table_invoices", "WritesTo"),
        ("proc_invoice", "proc_payment", "Executes"),
        ("proc_validate_token", "table_tokens", "ReadsFrom"),
        ("proc_fraud", "table_payments", "ReadsFrom"),
        ("proc_fraud", "table_acl", "ReadsFrom"),
        ("view_finance", "table_payments", "ReadsFrom"),
        ("view_finance", "table_invoices", "ReadsFrom"),
    ]
    if release == "1.1":
        edges += [
            ("proc_hybrid", "proc_vector_fallback", "Executes"),
            ("proc_vector_fallback", "view_shipments", "ReadsFrom"),
            ("proc_vector_fallback", "table_audit", "WritesTo"),
        ]

    # Add noisy but connected edges.
    extra_keys = [k for k in key_to_node if k.startswith("extra_sql_")]
    rng.shuffle(extra_keys)
    for i, key in enumerate(extra_keys):
        target = "table_payments" if i % 2 == 0 else "table_shipments"
        relation = "ReadsFrom" if i % 3 else "WritesTo"
        edges.append((key, target, relation))
        if i % 5 == 0:
            edges.append((key, "proc_hybrid", "Executes"))

    edge_rows: List[Dict[str, str]] = []
    for frm, to, relation in edges:
        if frm not in key_to_node or to not in key_to_node:
            continue
        to_kind = key_to_node[to].kind
        edge_rows.append(
            {
                "from": key_to_node[frm].obj["key"],
                "to": key_to_node[to].obj["key"],
                "relation": relation,
                "to_kind": to_kind,
                "file": key_to_node[frm].file,
                "batch": "fake-enterprise",
            }
        )

    node_rows: List[Dict[str, str]] = []
    for n in nodes:
        node_rows.append(
            {
                "key": n.obj["key"],
                "kind": n.kind,
                "name": n.name,
                "schema": n.schema,
                "file": n.file,
                "batch": "fake-enterprise",
                "domain": "sql",
                "body_path": "",
            }
        )

    return nodes, edge_rows, node_rows


def _assign_security_distribution(
    *,
    docs: List[Dict[str, object]],
    rng: random.Random,
) -> None:
    total = len(docs)
    n_none = int(total * 0.70)
    n_acl = int(total * 0.15)
    n_cls = int(total * 0.10)
    n_both = total - n_none - n_acl - n_cls

    categories = (["none"] * n_none) + (["acl"] * n_acl) + (["cls"] * n_cls) + (["both"] * n_both)
    rng.shuffle(categories)

    for doc, cat in zip(docs, categories):
        acl: List[str] = []
        cls: List[str] = []
        owner = ""
        if cat in ("acl", "both"):
            acl = sorted(set(rng.sample(ACL_TAGS, k=1 if rng.random() < 0.65 else 2)))
        if cat in ("cls", "both"):
            cls = sorted(set(rng.sample(CLASSIFICATION_LABELS, k=1 if rng.random() < 0.70 else 2)))
            owner = rng.choice(OWNER_IDS)
        doc["acl_tags_any"] = acl
        doc["classification_labels_all"] = cls
        doc["owner_id"] = owner


def _csv_to_text(rows: List[Dict[str, str]], fieldnames: List[str]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue()


def _build_release_bundle(release: str, out_dir: Path) -> Path:
    rng = random.Random(7000 + sum(ord(c) for c in release))
    root_name = f"Release_FAKE_ENTERPRISE_{release}"
    bundle_path = out_dir / f"{root_name}.zip"

    cs_nodes, cs_deps = _build_cs_release(release, rng)
    sql_nodes, sql_edges, sql_node_rows = _build_sql_release(release, rng)

    all_docs = [n.obj for n in cs_nodes] + [n.obj for n in sql_nodes]
    _assign_security_distribution(docs=all_docs, rng=rng)

    repo = "Fake"
    branch = f"release-{release}"
    snapshot_id = _head_sha(f"{repo}:{release}")
    meta = {
        "Branch": branch,
        "HeadSha": snapshot_id,
        "SnapshotId": snapshot_id,
        "RepositoryRoot": f"D:/Fake/{repo}",
        "Repo": repo,
        "GeneratedAtUtc": _utc_now(),
    }

    chunks_json = json.dumps([n.obj for n in cs_nodes], ensure_ascii=False, indent=2)
    deps_json = json.dumps(cs_deps, ensure_ascii=False, indent=2)
    sql_jsonl = "\n".join(json.dumps(n.obj, ensure_ascii=False) for n in sql_nodes) + "\n"
    edges_csv = _csv_to_text(sql_edges, ["from", "to", "relation", "to_kind", "file", "batch"])
    nodes_csv = _csv_to_text(sql_node_rows, ["key", "kind", "name", "schema", "file", "batch", "domain", "body_path"])
    manifest = json.dumps(
        {
            "release": release,
            "repo": repo,
            "source_system_id": "code",
            "notes": "English-only fake enterprise dataset for integration retrieval tests.",
        },
        ensure_ascii=False,
        indent=2,
    )
    readme = (
        "FakeEnterprise test bundle\n"
        "- English-only content\n"
        "- Mixed C# and SQL dependencies\n"
        "- Security metadata distribution: 70% none, 15% ACL only, 10% classification only, 5% both\n"
    )

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        prefix = f"{root_name}/"
        zf.writestr(prefix, "")
        zf.writestr(prefix + "repo_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        zf.writestr(prefix + "regular_code_bundle/", "")
        zf.writestr(prefix + "regular_code_bundle/chunks.json", chunks_json)
        zf.writestr(prefix + "regular_code_bundle/dependencies.json", deps_json)
        zf.writestr(prefix + "regular_code_bundle/README_WSL.txt", readme)
        zf.writestr(prefix + "sql_bundle/", "")
        zf.writestr(prefix + "sql_bundle/manifest.json", manifest)
        zf.writestr(prefix + "sql_bundle/docs/", "")
        zf.writestr(prefix + "sql_bundle/docs/sql_bodies.jsonl", sql_jsonl)
        zf.writestr(prefix + "sql_bundle/graph/", "")
        zf.writestr(prefix + "sql_bundle/graph/edges.csv", edges_csv)
        zf.writestr(prefix + "sql_bundle/graph/nodes.csv", nodes_csv)

    return bundle_path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "tests" / "repositories" / "fake"
    out_dir.mkdir(parents=True, exist_ok=True)

    generated = [
        _build_release_bundle("1.0", out_dir),
        _build_release_bundle("1.1", out_dir),
    ]
    for p in generated:
        print(f"generated: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
