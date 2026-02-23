# Retrieval Integration Test Specification (Implementation-Oriented)

## 1) Overview
This document specifies an implementation-oriented integration test suite for the retrieval subsystem backed by Weaviate. It is designed to be directly usable for implementing or validating tests in this repository.

In scope for this suite:
1. End-to-end retrieval correctness with deterministic Top‑5 ranking (BM25, semantic, hybrid) against fixed corpora.
2. SnapshotSet bootstrap and scope enforcement.
3. Security‑first filtering for ACL, clearance level, and classification labels.
4. Dependency graph expansion with security trimming and travel‑permission behavior.
5. Fetch‑node‑texts ordering and deterministic materialization.
6. Deterministic logging artifacts for every run.

Out of scope for this suite:
1. LLM answer quality and rendering.
2. UI behavior and frontend pipelines.
3. Embedding model accuracy beyond reproducibility.

Where to look in code:
`tests/integration/retrival/`
`code_query_engine/pipeline/actions/search_nodes.py`
`code_query_engine/pipeline/actions/expand_dependency_tree.py`
`code_query_engine/pipeline/actions/fetch_node_texts.py`
`code_query_engine/pipeline/providers/weaviate_retrieval_backend.py`
`code_query_engine/pipeline/providers/weaviate_graph_provider.py`

---

## 2) Round Harness (4 Rounds)
Each round is a full, clean integration run. The test runner must start with a fresh Weaviate container, import the round-specific bundles, create a SnapshotSet, run pytest, collect logs and traces, and finally destroy the container with volumes. Bundles are generated at session start and deleted after tests.

Canonical round lifecycle (near-pseudocode):
1. Generate fake bundles (autouse fixture) via `python -m tools.generate_retrieval_corpora_bundles`.
2. For each round parameter:
   1. Write `permissions` into `config.json` and `tests/config.json`.
   2. Export `ACL_ENABLED` and `REQUIRE_TRAVEL_PERMISSION` env overrides.
   3. Start Weaviate container via `docker run` on free ports.
   4. Wait for readiness (`/v1/.well-known/ready`).
   5. Import the two bundles for the round using `tools.weaviate.import_branch_to_weaviate`.
   6. Create SnapshotSet `Fake_snapshot` with `tools.weaviate.snapshot_sets add`.
   7. Run `pytest -m integration tests/integration/retrival`.
   8. Collect logs under `log/integration/retrival/`.
   9. Stop and remove the container.
3. After the session, delete all generated bundle ZIPs.
4. Restore original `config.json` and `tests/config.json`.

Implementation anchors used by the current codebase:
1. Autouse bundle generation/cleanup: `tests/integration/retrival/conftest.py::_generate_fake_bundles`.
2. Per-round config mutation: `tests/integration/retrival/conftest.py::_write_permissions_config`.
3. Weaviate lifecycle: `tests/integration/retrival/conftest.py::retrieval_integration_env`.
4. Readiness check: `tests/integration/retrival/conftest.py::_wait_for_weaviate_ready`.
5. Import entrypoint: `python -m tools.weaviate.import_branch_to_weaviate` (called in the fixture).
6. SnapshotSet creation: `python -m tools.weaviate.snapshot_sets add` (called in the fixture).
7. Snapshot resolution: `server/snapshots/snapshot_registry.py::SnapshotRegistry`.

Round definitions:

Round I
permissions:
`permissions.security_enabled = false`
`permissions.acl_enabled = false`
`permissions.require_travel_permission = false`
bundles:
`tests/repositories/fake/Release_FAKE_ENTERPRISE_1.0.zip`
`tests/repositories/fake/Release_FAKE_ENTERPRISE_1.1.zip`

Round II
permissions:
`permissions.security_enabled = true`
`permissions.acl_enabled = true`
`permissions.require_travel_permission = true`
`permissions.security_model.kind = "clearance_level"`
bundles:
`tests/repositories/fake/Release_FAKE_ENTERPRISE_2.0.zip`
`tests/repositories/fake/Release_FAKE_ENTERPRISE_2.1.zip`

Round III
permissions:
`permissions.security_enabled = true`
`permissions.acl_enabled = true`
`permissions.require_travel_permission = false`
`permissions.security_model.kind = "labels_universe_subset"`
bundles:
`tests/repositories/fake/Release_FAKE_ENTERPRISE_3.0.zip`
`tests/repositories/fake/Release_FAKE_ENTERPRISE_3.1.zip`

Round IV
permissions:
`permissions.security_enabled = false`
`permissions.acl_enabled = true`
`permissions.require_travel_permission = true`
bundles:
`tests/repositories/fake/Release_FAKE_ENTERPRISE_4.0.zip`
`tests/repositories/fake/Release_FAKE_ENTERPRISE_4.1.zip`

Where to look in code:
`tests/integration/retrival/conftest.py::ROUNDS`
`tests/integration/retrival/conftest.py::retrieval_integration_env`
`tools/generate_retrieval_corpora_bundles.py`

---

## 3) Data Profile Requirements and Verification
The imported datasets must satisfy these conditions per round:
1. Round I: no ACL data, no `clearance_level`, no `classification_labels` in any node.
2. Round II: ACL present, `clearance_level` present, no `classification_labels`.
3. Round III: ACL present, `classification_labels` present, no `clearance_level`.
4. Round IV: ACL present, no `clearance_level`, no `classification_labels`.

Field mapping and schema anchors:
1. Bundle fields `acl_tags_any` map to Weaviate property `acl_allow` in `tools/weaviate/import_branch_to_weaviate.py::iter_cs_nodes` and `::_iter_sql_nodes_from_jsonl`.
2. Bundle fields `classification_labels_all` map to Weaviate property `classification_labels` in the same functions.
3. Bundle field `clearance_level` maps to Weaviate property `doc_level` in the same functions (`doc_level_raw = d.get("doc_level") or d.get("clearance_level")`).
4. RagNode schema properties are created in `tools/weaviate/import_branch_to_weaviate.py::ensure_schema`.
5. ACL schema creation is gated by `permissions.acl_enabled` in `tools/weaviate/import_branch_to_weaviate.py::_is_acl_enabled`.

Verification steps that must be executed in each round:
1. Query RagNode schema and assert property presence or absence.
2. Fetch a sample of nodes and assert values are present or missing according to the round’s profile.

Where to look in code:
`tools/weaviate/import_branch_to_weaviate.py::ensure_schema`
`tools/weaviate/import_branch_to_weaviate.py::iter_cs_nodes`
`tools/weaviate/import_branch_to_weaviate.py::_iter_sql_nodes_from_jsonl`
`tests/integration/retrival/helpers.py::load_bundle_metadata`

---

## 4) Logging Contract (Critical)
The suite must always produce deterministic logs and traces for every run.

Required log files and patterns:
1. Consolidated test results log, latest:
`log/integration/retrival/test_results_latest.log`
2. Consolidated test results log, archived per run:
`log/integration/retrival/test_results_<TIMESTAMP>.log`
3. Pipeline trace per query:
`log/integration/retrival/pipeline_traces/<TIMESTAMP>_<search_type>_<query>.json`
4. Dependency tree report:
`log/integration/retrival/graph_results_latest.log` and `graph_results_<TIMESTAMP>.log`
5. Fetch‑node‑texts report:
`log/integration/retrival/fetch_texts_results_latest.log` and `fetch_texts_results_<TIMESTAMP>.log`
6. Contract/fail‑fast report:
`log/integration/retrival/contract_gap_results_latest.log` and `contract_gap_results_<TIMESTAMP>.log`

Log producers and field requirements (new tests):
1. `tests/integration/retrival/test_search_and_fetch.py::_write_expectations_report`
   - Required fields per entry:
     `Round`, `Question`, `Search mode`, `Applied filters`, `Observed results`, `Observed security`.
2. `tests/integration/retrival/helpers.py::write_pipeline_trace`
   - Required JSON fields:
     `generated_utc`, `query`, `search_type`, `retrieval_filters`, `observed_sources`.
3. `tests/integration/retrival/test_dependency_tree.py::_write_graph_report`
   - Required fields per entry:
     `Case`, `Round`, `Seed IDs`, `Expected node IDs`, `Observed node IDs`.
4. `tests/integration/retrival/test_fetch_node_texts.py::_append_fetch_row`
   - Required fields per entry:
     `Case`, `Round`, `Expected order`.
5. `tests/integration/retrival/test_contracts.py::_write_report`
   - Required fields per entry:
     `Case`, `Round`, `Status`, `Expected`, `Observed`.

Where to look in code:
`tests/integration/retrival/test_search_and_fetch.py::_write_expectations_report`
`tests/integration/retrival/helpers.py::write_pipeline_trace`
`tests/integration/retrival/test_dependency_tree.py::_write_graph_report`
`tests/integration/retrival/test_fetch_node_texts.py::_append_fetch_row`
`tests/integration/retrival/test_contracts.py::_write_report`

---

## 5) Golden Results Source (Top‑5 Ranking)
The Top‑5 expected results are defined in:
`tests/integration/fake_data/retrieval_results_top5_corpus1_corpus2.md`

Tests that validate Top‑5 ranking must parse this file and must not invent or hardcode expected IDs beyond what is declared in the file.

Mapping from golden item numbers to repository paths:
1. C# corpus item `NNN` maps to file `src/FakeEnterprise.Corpus/CSharp/CorpusItemNNN.cs`.
2. C# corpus item `NNN` maps to local id `C{NNNN}` and therefore to canonical id `Fake::<snapshot>::cs::C{NNNN}`.
3. SQL corpus item `NNN` maps to file `db/procs/proc_Corpus_NNN.sql`.
4. SQL corpus item `NNN` maps to SQL key `SQL:dbo.proc_Corpus_NNN` and therefore to canonical id `Fake::<snapshot>::sql::SQL:dbo.proc_Corpus_NNN`.

Parsing and conversion are implemented in:
`tests/integration/retrival/helpers.py::parse_golden_results`

---

## 6) Travel Permission Behavior (Required)
Travel permission affects graph expansion after ACL/security filters.

Implementation anchors:
1. Enforcement switch: `code_query_engine/pipeline/actions/expand_dependency_tree.py::_require_travel_permission`.
2. Pruning implementation: `code_query_engine/pipeline/actions/expand_dependency_tree.py::_apply_travel_permission`.
3. Security filter applied before pruning: `code_query_engine/pipeline/providers/weaviate_graph_provider.py::filter_by_permissions`.

Observable behavior required in tests:
1. When `require_travel_permission=true`, graph expansion must not include nodes that are only reachable via a denied node, even if those nodes are individually allowed by ACL or security filters.
2. When `require_travel_permission=false`, graph expansion may include allowed nodes even if an intermediate node was denied, as long as they are connected through the raw graph.
3. No dangling edges are allowed after trimming; all edges must connect two visible nodes.

---

## 7) Test Cases (Mapped to New Tests)

### IT‑001 `test_snapshot_set_exists`
A) Validation goal: SnapshotSet exists and references imported bundles.
B) Inputs: Round I–IV bundles; SnapshotSet collection; snapshot_set_id `Fake_snapshot`.
C) Steps:
1. Connect to Weaviate.
2. Fetch `SnapshotSet` by `snapshot_set_id`.
3. Assert repo name, allowed refs, snapshot IDs, `is_active`.
D) Expected outputs per round:
Round I–IV: SnapshotSet exists with both refs from the round.
E) Logged outputs:
No log entry is produced by this test.
F) Where to look: `tests/integration/retrival/test_bootstrap.py::test_snapshot_set_exists`.

### IT‑002 `test_import_runs_completed`
A) Validation goal: ImportRun entries exist for all imported refs.
B) Inputs: Round I–IV bundles; ImportRun collection.
C) Steps:
1. Connect to Weaviate.
2. Query ImportRun for repo + status=completed.
3. Verify all `env.imported_refs` are present.
D) Expected outputs per round:
Round I–IV: All refs exist with status completed.
E) Logged outputs:
No log entry is produced by this test.
F) Where to look: `tests/integration/retrival/test_bootstrap.py::test_import_runs_completed`.

### IT‑003 `test_search_then_fetch_matches_expected_markers`
A) Validation goal: End‑to‑end search + fetch returns Top‑5 in exact order for each query/mode/corpus, after applying per‑round security filters.
B) Inputs:
- Query cases parsed from golden file.
- `search_type` in {bm25, semantic, hybrid}.
- `top_k=5`, `budget_tokens=6000`, `prioritization_mode=seed_first`.
- Filters:
  - Always: `source_system_id` (csharp or sql)
  - Round I: no ACL, no security model
  - Round II: ACL + clearance (user_level=10)
  - Round III: ACL + labels (`public,internal,restricted`)
  - Round IV: ACL only
C) Steps:
1. Parse golden file into QueryCase list.
2. For each case, run search_nodes then fetch_node_texts.
3. Compute expected sources from golden Top‑5 filtered by round permissions.
4. Assert observed sources match expected exactly (order + length).
D) Expected outputs per round:
- Round I: observed sources == golden Top‑5.
- Round II: observed sources == golden Top‑5 filtered by ACL + clearance.
- Round III: observed sources == golden Top‑5 filtered by ACL + labels.
- Round IV: observed sources == golden Top‑5 filtered by ACL only.
E) Logged outputs:
In `log/integration/retrival/test_results_latest.log` each entry must include:
- `Round : <round-id>`
- `Question : <query>`
- `Search mode : <bm25|semantic|hybrid>`
- `Applied filters : { ... }` (exact JSON)
- `Observed results : <ordered list of source_file>`
- `Observed security : <source_file [acl=... | cls=...]>`
Pipeline trace per query:
`log/integration/retrival/pipeline_traces/<timestamp>_<search_type>_<query>.json` with fields:
`generated_utc`, `query`, `search_type`, `retrieval_filters`, `observed_sources`.
F) Where to look: `tests/integration/retrival/test_search_and_fetch.py::test_search_then_fetch_matches_expected_markers` and `tests/integration/retrival/helpers.py`.

### IT‑004 `test_dependency_tree_allowlist_expected_outputs`
A) Validation goal: Graph expansion respects allowlist and max_depth.
B) Inputs:
- C# graph case: seed `C0001`, allowlist `cs_dep`, max_depth=2.
- SQL graph case: seed `SQL:dbo.proc_Corpus_001`, allowlist `sql_Calls`, max_depth=2.
C) Steps:
1. Resolve primary snapshot ID.
2. Expand dependency tree.
3. Assert observed nodes match expected exact set.
D) Expected outputs per round:
Round I–IV: same graph behavior (no security filters in this test).
E) Logged outputs:
In `log/integration/retrival/graph_results_latest.log` and `test_results_latest.log`, entries must include:
`Case`, `Round`, `Seed IDs`, `Expected node IDs`, `Observed node IDs`.
F) Where to look: `tests/integration/retrival/test_dependency_tree.py::test_dependency_tree_allowlist_expected_outputs`.

### IT‑005 `test_expand_dependency_tree_travel_permission`
A) Validation goal: travel permission enforcement changes reachable graph nodes.
B) Inputs:
- Seed `C0001`, allowlist `cs_dep`, max_depth=6.
- ACL filters = `finance, security`.
C) Steps:
1. Expand dependency tree with ACL filters.
2. If `require_travel_permission=true`, only seed remains.
3. If `require_travel_permission=false`, reachable nodes beyond denied nodes are allowed.
D) Expected outputs per round:
- Round I: skipped (ACL disabled).
- Round II: require_travel_permission=true → expected nodes: only seed.
- Round III: require_travel_permission=false → expected nodes: seed + C0006 + C0007.
- Round IV: require_travel_permission=true → expected nodes: only seed.
E) Logged outputs:
Same as IT‑004 (graph log entry for `Case : travel_permission`).
F) Where to look: `tests/integration/retrival/test_dependency_tree.py::test_expand_dependency_tree_travel_permission`.

### IT‑006 `test_fetch_node_texts_order_and_limits`
A) Validation goal: fetch_node_texts ordering obeys prioritization mode.
B) Inputs:
- Seeds: C0005, C0016, C0011
- Graph nodes: C0013, C0006, C0027
- Modes: seed_first, graph_first, balanced
C) Steps:
1. Prepare state with seeds, graph nodes, and edges.
2. Execute fetch_node_texts for each case.
3. Assert order equals expected.
D) Expected outputs per round:
Round I–IV: same behavior.
E) Logged outputs:
In `log/integration/retrival/fetch_texts_results_latest.log` (and merged into test_results_latest.log):
- `Case : F1/F2/F3/F4`
- `Round : <round-id>`
- `Expected order : <canonical ids>`
F) Where to look: `tests/integration/retrival/test_fetch_node_texts.py::test_fetch_node_texts_order_and_limits`.

### IT‑007 `test_search_nodes_missing_top_k`
A) Validation goal: missing top_k fails fast.
B) Inputs: search_nodes without top_k.
C) Expected error: `search_nodes: Missing required top_k (step.raw.top_k or pipeline_settings.top_k).`
D) Logged outputs:
In `log/integration/retrival/contract_gap_results_latest.log` and merged log:
- `Case : search_nodes_missing_top_k`
- `Status : pass`
- `Expected : <error>`
- `Observed : <same error>`
F) Where to look: `tests/integration/retrival/test_contracts.py::test_search_nodes_missing_top_k`.

### IT‑008 `test_search_nodes_unknown_search_type`
A) Validation goal: invalid search_type fails fast.
B) Expected error: `search_nodes: invalid search_type='unknown'`.
Logged outputs: same format in contract log.
F) Where to look: `tests/integration/retrival/test_contracts.py::test_search_nodes_unknown_search_type`.

### IT‑009 `test_search_nodes_rerank_only_for_semantic`
A) Validation goal: rerank not allowed for bm25/hybrid.
B) Expected error: `search_nodes: rerank='keyword_rerank' is only allowed for search_type='semantic' (contract).`.
Logged outputs: same format in contract log.
F) Where to look: `tests/integration/retrival/test_contracts.py::test_search_nodes_rerank_only_for_semantic`.

### IT‑010 `test_fetch_node_texts_budget_conflict`
A) Validation goal: budget_tokens + max_chars conflict fails fast.
B) Expected error: `fetch_node_texts: max_chars cannot be used together with budget_tokens (contract).`.
Logged outputs: same format in contract log.
F) Where to look: `tests/integration/retrival/test_contracts.py::test_fetch_node_texts_budget_conflict`.

### IT‑011 `test_expand_dependency_tree_missing_settings`
A) Validation goal: missing required settings keys fails fast.
B) Expected error: `expand_dependency_tree: Missing required 'max_depth_from_settings' in YAML step.`
Logged outputs: same format in contract log.
F) Where to look: `tests/integration/retrival/test_contracts.py::test_expand_dependency_tree_missing_settings`.

---

## 8) Notes on Determinism
1. Bundle generation uses deterministic seeds (`tools/generate_retrieval_corpora_bundles.py`), ensuring identical content across runs.
2. Canonical IDs are deterministic (`tools/weaviate/import_branch_to_weaviate.py::canonical_id`).
3. Golden Top‑5 values are fixed in `retrieval_results_top5_corpus1_corpus2.md`.
4. Log file content is deterministic and can be diffed across runs.

---

## 9) Appendix A — Golden Top‑5 Inputs
The exact Top‑5 expectations are defined in:
`tests/integration/fake_data/retrieval_results_top5_corpus1_corpus2.md`

For tests using Top‑5 (IT‑003), the expected `Observed results` log line must equal the ordered list of source files derived from that file (after applying per‑round security filtering).

Parsing and mapping are implemented in:
`tests/integration/retrival/helpers.py::parse_golden_results`
`tests/integration/retrival/helpers.py::_expected_sources`
