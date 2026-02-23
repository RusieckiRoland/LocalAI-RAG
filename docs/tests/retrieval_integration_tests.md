# Retrieval Integration Test Expectations (Fake Snapshot)

This document defines **expected outcomes** for the integration suite under:
- `tests/integration/retrival/test_bootstrap.py`
- `tests/integration/retrival/test_search_and_fetch.py`

It is intentionally result-focused, so you can compare real run output against a stable target.

## Test Dataset Scope
The integration suite imports fake bundles from:
- `tests/repositories/fake/Release_FAKE_ENTERPRISE_*.zip` (default)
- Override with `INTEGRATION_BUNDLE_GLOB` if needed.

Expected dataset characteristics:
- English content in code/text chunks.
- Mixed C# and SQL nodes.
- Dependency relations present (C# and SQL call/use chains).
- Security metadata distribution target in generated fake bundles:
  - ~70% no access tags
  - ~15% `acl_tags_any`
  - ~10% `doc_level` (clearance_level)
  - ~5% both `acl_tags_any` and `doc_level`

## Run Command
From repository root:

```bash
conda activate rag-weaviate
bash tools/run_retrival_integration_tests.sh
```

## Execution Sequence (Expected)
1. Start isolated Weaviate container on dynamic, non-conflicting ports.
2. Wait for Weaviate readiness.
3. Import fake bundles from `tests/repositories/fake`.
4. Create snapshot set `Fake_snapshot`.
5. Execute retrieval integration tests.
6. Write logs and pipeline traces under `log/integration/retrival`.
7. Tear down test container.

## Expected Outcomes - Bootstrap Layer

### B1
Test: `test_fake_snapshot_set_exists`
Expected outcome:
- `Fake_snapshot` exists.
- It resolves to imported fake references.

### B2
Test: `test_import_runs_are_completed`
Expected outcome:
- Import jobs complete successfully.
- No partial/failed import state.

### B3 (Added after security review)
Test group: `test_import_rejects_invalid_security_inputs`
Purpose: validate importer rejects invalid security configuration/data inputs.
Expected outcome:
1. If `permissions.acl_enabled=true` and any document is missing `acl_allow`, import fails with a clear error.
2. If `permissions.security_enabled=true` and `permissions.security_model` is missing, import fails with a clear error.
3. If `permissions.security_enabled=true` and `security_model.kind=labels_universe_subset` and any document is missing `classification_labels`, import fails with a clear error.
4. If `permissions.security_enabled=true` and `security_model.kind=clearance_level` and any document is missing `doc_level`, import fails with a clear error.

---

## Expected Outcomes - Retrieval Layer

General pass rule for each retrieval case:
1. `search_nodes` returns at least one seed node.
2. `fetch_node_texts` returns non-empty texts.
3. At least one expected marker is found in fetched text.

Expected retrieval cases are grouped below.

### 1) Semantic (5)

#### 1.1
Question: `Where is the application entry point and bootstrap?`
Expected result markers:
- `point, entry point`
- `bootstrap`
Expected source candidates:
- `Program.cs`
- `AppBootstrap.cs`
- `QueryRouter.cs`

#### 1.2
Question: `How does semantic search and nearest neighbors work?`
Expected result markers:
- `semantic search`
- `nearest neighbors`
Expected source candidates:
- `SemanticSearcher.cs`
- `EmbeddingModel.cs`
- `NearestNeighbors.cs`
- `CosineSimilarity.cs`

#### 1.3
Question: `Which component combines BM25 and semantic search?`
Expected result markers:
- `bm25`
- `semantic`
- `hybrid`
Expected source candidates:
- `HybridRanker.cs`
- `ReciprocalRankFusion.cs`
- `KeywordRerankScorer.cs`
- `SearchFacade.cs`

#### 1.4
Question: `Where is fraud risk calculated with token validation?`
Expected result markers:
- `fraud, risk score`
- `token validation`
Expected source candidates:
- `FraudRiskScorer.cs`
- `TokenValidator.cs`
- `proc_ComputeFraudRisk.sql`

#### 1.5
Question: `How do we search shipments by tracking number?`
Expected result markers:
- `tracking number`
- `shipment`
Expected source candidates:
- `ShipmentService.cs`
- `ShipmentRepository.cs`
- `proc_GetShipmentByTracking.sql`
- `view_Shipments.sql`

---

### 2) BM25 (5)

#### 2.1
Query: `proc_SearchShipments_BM25`
Expected result markers:
- `proc_SearchShipments_BM25`
Expected source candidates:
- `proc_SearchShipments_BM25.sql`

#### 2.2
Query: `KeywordExtractor ExtractKeywords`
Expected result markers:
- `ExtractKeywords`
Expected source candidates:
- `KeywordExtractor.cs`
- `Bm25Searcher.cs`

#### 2.3
Query: `TokenValidator ValidateToken`
Expected result markers:
- `ValidateToken`
- `signature verification`
Expected source candidates:
- `TokenValidator.cs`
- `proc_ValidateToken.sql`

#### 2.4
Query: `table_Payments proc_ProcessPayment`
Expected result markers:
- `table_Payments`
- `proc_ProcessPayment`
- `PaymentService`
- `proc_GenerateInvoice`
Expected source candidates:
- `table_Payments.sql`
- `proc_ProcessPayment.sql`
- `PaymentService.cs`
- `proc_GenerateInvoice.sql`

#### 2.5
Query: `DependencyTreeExpander`
Expected result markers:
- `DependencyTreeExpander`
Expected source candidates:
- `DependencyTreeExpander.cs`
- `GraphProviderFacade.cs`

---

### 3) Hybrid (5)

#### 3.1
Question: `hybrid search BM25 semantic rerank shipments`
Expected result markers:
- `hybrid`
- `bm25`
- `semantic`
Expected source candidates:
- `HybridRanker.cs`
- `SearchFacade.cs`
- `proc_SearchShipments_Hybrid.sql`

#### 3.2
Question: `ACL filter before rank`
Expected result markers:
- `acl`
- `filter`
- `permissions`
Expected source candidates:
- `AclFilter.cs`
- `AclPolicy.cs`
- `SearchFacade.cs`

#### 3.3
Question: `payments invoices VAT`
Expected result markers:
- `payment`
- `invoice`
- `vat`
Expected source candidates:
- `PaymentService.cs`
- `InvoiceGenerator.cs`
- `VatCalculator.cs`
- `table_Payments.sql`

#### 3.4
Question: `who calls stored procedure execute`
Expected result markers:
- `stored procedure`
- `SqlExecutor`
Expected source candidates:
- `SqlExecutor.cs`
- `ShipmentService.cs`
- `PaymentService.cs`

#### 3.5
Question: `query routing and retrieval strategy selection`
Expected result markers:
- `route request`
- `search facade`
Expected source candidates:
- `QueryRouter.cs`
- `QueryParser.cs`
- `SearchFacade.cs`

---

### 4) Secondary Snapshot Path

#### 4.1
Question: `token validation and auth`
Search mode: `semantic`
Snapshot source: `secondary`
Expected result markers:
- `token validation`
- `jwt`
Expected outcome:
- Query is executed against `snapshot_id_b` path.
- At least one token-related source/text is returned.

## Log Artifacts To Compare
After run, compare these files:
- `log/integration/retrival/test_results_latest.log`
- `log/integration/retrival/pipeline_traces/latest.json`
- `log/integration/retrival/pipeline_traces/*.json`

The human-readable check should always include:
1. `Question`
2. `Search mode`
3. `Applied filters`
4. `Observed results`
5. `Observed security`

## Pass/Fail Interpretation
Pass means:
1. Bootstrap tests pass.
2. Retrieval tests pass for semantic, bm25, hybrid, and secondary snapshot path.
3. Log artifacts are generated in the integration log directory.

Fail means:
1. Missing snapshot set/import.
2. Empty seed nodes/texts.
3. Expected markers not found.
4. Missing integration trace artifacts.

---

## 5) Security Filter Scenarios (ACL + Clearance Level)

This section defines expected behavior when security filters are present in `retrieval_filters`
for the **clearance_level** model (when `permissions.security_model.kind=clearance_level`).

### Security Logic Contract (clearance_level)
1. `acl_tags_any` is evaluated as OR (if `permissions.acl_enabled=true`).
2. `user_level` is evaluated as `doc_level <= user_level`.
3. If both are present, effective rule is:
   - `(document.acl intersects user.acl_tags_any)` AND `(doc_level <= user_level)`
4. Empty ACL is allowed by default.
5. If `allow_missing_doc_level=true`, missing `doc_level` is treated as public.
6. Importer rule:
   - If `acl_enabled=true`, importer MUST write `acl_allow` for every document (attribute present even if empty `[]`). Missing `acl_allow` must fail import/ingestion.
   - If `acl_enabled=false`, importer MUST NOT write `acl_allow`.
   - `doc_level` is written **only when** `security_model.kind=clearance_level`.

### Expected Trace Fields
When security scenarios are executed, `state_after.retrieval_filters` should include:
1. `repo`
2. `snapshot_id` (or `snapshot_ids_any`)
3. `acl_tags_any` (only if ACL is enabled)
4. `user_level` (only for clearance_level)

Example:

```json
{
  "repo": "Fake",
  "snapshot_id": "<resolved_snapshot_id>",
  "acl_tags_any": ["finance", "security"],
  "user_level": 10
}
```

### Expected Behavior Matrix (clearance_level)

#### Clearance-only scenario (ACL disabled)
Assume `acl_enabled=false`, `allow_missing_doc_level=true`.
Expected:
1. `doc_level=0`, `user_level=0` -> visible.
2. `doc_level=10`, `user_level=0` -> not visible.
3. `doc_level=None`, `user_level=0` -> visible.

#### ACL + clearance scenario (ACL enabled)
User ACL: `["finance", "security"]`
User level: `10`
Expected:
1. Doc ACL `["finance"]`, `doc_level=10` -> visible.
2. Doc ACL `["hr"]`, `doc_level=10` -> not visible (ACL fail).
3. Doc ACL `["finance"]`, `doc_level=20` -> not visible (clearance fail).

### Result Interpretation in Logs
For security cases, compare:
1. `retrieval_filters` in pipeline trace (`log/integration/retrival/pipeline_traces/*.json`).
2. `Observed results` in `log/integration/retrival/test_results_latest.log`.
3. Presence/absence of expected sources for each scenario.

Security tests pass when:
1. The expected filter fields are present in trace.
2. Allowed documents are retrievable.
3. Disallowed documents are consistently excluded.
4. `Observed security` in `test_results_latest.log` confirms ACL and `doc_level` for returned documents.

---

## 6) Dependency Tree Expansion Scenarios

This section defines expected behavior for integration tests that validate dependency-tree construction after retrieval.

### Tree Expansion Contract
1. The graph tree must be expanded from seed nodes to the depth configured in pipeline settings.
2. Full expansion means:
   - all reachable dependencies are included up to `graph_max_depth`,
   - unless hard limits (`graph_max_nodes`, relation allowlist) stop expansion.
3. Tree expansion must respect pipeline limits and relation filters.
4. Final tree must be security-trimmed:
   - nodes violating `acl_tags_any` access must be excluded,
   - nodes violating `classification_labels_all` access must be excluded.

### Pipeline-Limit Scenarios (Expected)
For test scenarios with constrained graph settings, expected behavior:
1. `graph_max_depth: 2`
   - no node beyond depth 2 appears in final tree.
2. `graph_max_nodes: 120`
   - total expanded nodes must not exceed 120.
3. `graph_edge_allowlist`:
   - only allowed relations may appear in expanded edges,
   - disallowed relation types must not appear.

Example allowlist:

```yaml
graph_max_depth: 2
graph_max_nodes: 120
graph_edge_allowlist:
  - "ReadsFrom"
  - "WritesTo"
  - "Calls"
  - "Executes"
  - "FK"
  - "On"
  - "SynonymFor"
  - "ReferencedBy(C#)"
```

### Security Trimming Requirements
After expansion (before final output), tree must be filtered by security rules:
1. ACL rule: OR semantics for `acl_tags_any`.
2. Classification rule: AND semantics for `classification_labels_all`.
3. Effective rule when both are present:
   - `(ACL OR)` AND `(Classification AND)`.
4. Result:
   - disallowed nodes are removed from final node set,
   - edges referencing removed nodes are also removed.

### What to Verify in Logs
For dependency-tree tests, compare:
1. Pipeline settings used for graph expansion (`graph_max_depth`, `graph_max_nodes`, `graph_edge_allowlist`).
2. Seed nodes from retrieval step.
3. Final expanded node count and edge count.
4. Relation types present in final edges.
5. Security-trim effect:
   - nodes/edges removed due to ACL/classification.

Recommended evidence artifacts:
1. `log/integration/retrival/test_results_latest.log`
2. `log/integration/retrival/pipeline_traces/latest.json`
3. Per-case traces in `log/integration/retrival/pipeline_traces/*.json`
4. `log/integration/retrival/graph_results_latest.log`

### Concrete Expected Cases (seed IDs -> expected expansion IDs)

Note:
1. For C# nodes, expected IDs are `Cxxxx` canonical IDs.
2. For SQL nodes, expected IDs are SQL canonical IDs (`SQL:<schema>.<name>`).
3. Text loading is a separate step (`fetch_node_texts`), so this section validates ID-level graph expansion only.

### Expected Outputs (allowlist sensitivity)

Seed ID:
- `SQL:dbo.proc_ProcessPayment`

Two variants are expected and must be checked:
1. Depth-limited expansion (`graph_max_depth=1`) with standard BFS behavior.
2. Seed-only expansion (emit only edges originating from the seed node, no secondary fan-out).

The expected node/edge sets below are the same for both variants, but **seed-only** adds an extra constraint:
- No edge in the final output may have `from_id` different from the seed node.

#### A) Full allowlist (default)
Allowed relations:
- `ReadsFrom`, `WritesTo`, `Calls`, `Executes`, `FK`, `On`, `SynonymFor`, `ReferencedBy(C#)`
Graph limit:
- `graph_max_depth: 1` (limit expansion to seed + direct neighbors)

Expected nodes:
1. `SQL:dbo.proc_ProcessPayment` (seed)
2. `SQL:dbo.table_Payments`
3. `SQL:dbo.proc_ValidateToken`
4. `SQL:dbo.proc_ComputeFraudRisk`

Expected edges:
1. `SQL:dbo.proc_ProcessPayment` --`WritesTo`--> `SQL:dbo.table_Payments`
2. `SQL:dbo.proc_ProcessPayment` --`Executes`--> `SQL:dbo.proc_ValidateToken`
3. `SQL:dbo.proc_ProcessPayment` --`Executes`--> `SQL:dbo.proc_ComputeFraudRisk`
Seed-only constraint:
- All edges must have `from_id = SQL:dbo.proc_ProcessPayment` (no edges originating from `table_Payments` or any other node).

#### B) Limited allowlist (ReadsFrom / WritesTo / Calls)
Allowed relations:
- `ReadsFrom`, `WritesTo`, `Calls`
Graph limit:
- `graph_max_depth: 1`

Expected nodes:
1. `SQL:dbo.proc_ProcessPayment` (seed)
2. `SQL:dbo.table_Payments`

Expected edges:
1. `SQL:dbo.proc_ProcessPayment` --`WritesTo`--> `SQL:dbo.table_Payments`
Seed-only constraint:
- All edges must have `from_id = SQL:dbo.proc_ProcessPayment`.

#### C) Write-only allowlist (WritesTo)
Allowed relations:
- `WritesTo`
Graph limit:
- `graph_max_depth: 1`

Expected nodes:
1. `SQL:dbo.proc_ProcessPayment` (seed)
2. `SQL:dbo.table_Payments`

Expected edges:
1. `SQL:dbo.proc_ProcessPayment` --`WritesTo`--> `SQL:dbo.table_Payments`
Seed-only constraint:
- All edges must have `from_id = SQL:dbo.proc_ProcessPayment`.

#### D1. Full C# tree from retrieval core (`SearchFacade.cs`)
Seed node IDs:
1. `C0005`

Expected depth-1 node IDs:
1. `C0006`
2. `C0011`
3. `C0016`
4. `C0019`

Expected depth-2 node IDs:
1. `C0007`
2. `C0008`
3. `C0009`
4. `C0010`
5. `C0012`
6. `C0013`
7. `C0014`
8. `C0015`
9. `C0017`
10. `C0018`
11. `C0020`

#### D2. SQL tree from hybrid procedure (`proc_SearchShipments_Hybrid.sql`)
Seed node IDs:
1. `SQL:dbo.proc_SearchShipments_Hybrid`

Expected depth-1 node IDs:
1. `SQL:dbo.proc_SearchShipments_BM25` (relation: `Executes`)
2. `SQL:dbo.proc_SearchShipments_Semantic` (relation: `Executes`)

Expected depth-2 node IDs:
1. `SQL:dbo.view_Shipments` (relation: `ReadsFrom`)

#### D3. Pipeline-limited tree (`graph_max_depth=2`, `graph_max_nodes=120`)
Seed node IDs:
1. `C0003`

Expected depth-1 node IDs:
1. `C0004`
2. `C0005`

Expected depth-2 node IDs:
1. `C0006`
2. `C0011`
3. `C0016`
4. `C0019`

Must not appear:
1. Any node at depth >= 3 from this seed.
2. Any non-allowlisted edge type.

---


#### D4. Security-trimmed tree (ACL + classification)
Applied filters:
1. `acl_tags_any=["finance","security"]`
2. `classification_labels_all=["restricted"]`

Seed node IDs:
1. `C0005` (or equivalent seed IDs that reach mixed-security nodes)

Expected:
1. Returned/expanded nodes must satisfy ACL OR condition for `finance/security`.
2. Returned/expanded nodes must satisfy classification AND condition for `restricted`.
3. Example node IDs that can be excluded by ACL in baseline fake bundles:
   - `C0027` (non-matching ACL in generated releases)
   - `C0003` (tagged as `architecture`)
4. Edges pointing to excluded nodes must be removed from final tree output.

### Pass Criteria for Dependency-Tree Tests
Dependency-tree integration tests pass when:
1. Expansion depth does not exceed configured depth.
2. Node count does not exceed configured max nodes.
3. Only allowlisted edge relations are present.
4. Security-restricted nodes are excluded from final tree.
5. Final tree remains connected/usable for downstream context fetch.

---

## 7) Fetch Node Texts Scenarios

This section defines expected outcomes for `fetch_node_texts` behavior:
1. Correct text retrieval.
2. Correct prioritization (`seed_first` | `graph_first` | `balanced`).
3. Correct enforcement of limits (`max_chars`, `budget_tokens`, `budget_tokens_from_settings`).
4. Correct handling of **atomic skip** (a node is either fully included or fully skipped).

### Common Seed/Graph Dataset (stable IDs)
Use seed/graph IDs from the integration suite (IDs are canonical node IDs):
- Seeds: `C0005`, `C0006`, `C0011`, `C0016`
- Graph nodes: `C0007`, `C0008`, `C0009`, `C0010`, `C0012`, `C0013`

Expected text existence:
- Each listed ID above has non-empty `text` in Weaviate.

### F1. Text Retrieval Integrity (baseline)
Inputs:
1. `retrieval_seed_nodes`: `["C0005", "C0006"]`
2. `graph_expanded_nodes`: `[]`
3. `budget_tokens`: `300`
4. `prioritization_mode`: `seed_first`

Expected:
1. Returned texts correspond to seed IDs only.
2. `node_texts` contains non-empty `text` values.
3. No graph nodes included.

### F2. Prioritization: `seed_first`
Inputs:
1. `retrieval_seed_nodes`: `["C0005", "C0006", "C0011"]`
2. `graph_expanded_nodes`: `["C0007", "C0008", "C0009"]`
3. `budget_tokens`: small (low enough to include 2–3 nodes)
4. `prioritization_mode`: `seed_first`

Expected order:
1. Seed nodes appear first in `node_texts`.
2. Graph nodes only appear if token budget remains.

### F3. Prioritization: `graph_first`
Inputs:
1. `retrieval_seed_nodes`: `["C0005", "C0006"]`
2. `graph_expanded_nodes`: `["C0007", "C0008", "C0009"]`
3. `budget_tokens`: small (low enough to include 2–3 nodes)
4. `prioritization_mode`: `graph_first`

Expected order:
1. Graph nodes appear before seed nodes in `node_texts`.
2. Seed nodes only appear if token budget remains.

### F4. Prioritization: `balanced`
Inputs:
1. `retrieval_seed_nodes`: `["C0005", "C0006", "C0011"]`
2. `graph_expanded_nodes`: `["C0007", "C0008", "C0009"]`
3. `budget_tokens`: small (low enough to include 3–4 nodes)
4. `prioritization_mode`: `balanced`

Expected order:
1. Interleaving pattern: seed → graph → seed → graph (deterministic).
2. Both groups represented if budget allows.

### F5. Budget Tokens Limit
Inputs:
1. `retrieval_seed_nodes`: `["C0005", "C0006", "C0011"]`
2. `graph_expanded_nodes`: `["C0007", "C0008"]`
3. `budget_tokens`: very low (e.g., ~20–40 tokens)
4. `prioritization_mode`: `seed_first`

Expected:
1. Only the smallest set of nodes that fit in budget are returned.
2. Total token count of returned texts <= `budget_tokens`.

### F6. budget_tokens_from_settings
Inputs:
1. `budget_tokens_from_settings`: `node_text_fetch_top_n` or equivalent config mapping
2. `budget_tokens`: unset
3. `retrieval_seed_nodes` + `graph_expanded_nodes` same as F2/F3

Expected:
1. Budget is taken from settings.
2. Same ordering rules apply based on `prioritization_mode`.

### F7. max_chars Limit
Inputs:
1. `max_chars`: strict (low enough to include partial set only)
2. `retrieval_seed_nodes`: `["C0005", "C0006", "C0011"]`
3. `graph_expanded_nodes`: `["C0007", "C0008"]`
4. `prioritization_mode`: `seed_first`

Expected:
1. Total output characters <= `max_chars`.
2. Nodes beyond the limit are not included.

### F8. Atomic Skip Behavior
Definition:
- A node is either fully included or fully skipped (no partial truncation per node).

Inputs:
1. Use a tight `budget_tokens` or `max_chars` that would allow only part of the next node.
2. `retrieval_seed_nodes`: `["C0005", "C0006"]`
3. `graph_expanded_nodes`: `[]`
4. `prioritization_mode`: `seed_first`

Expected:
1. If the next node would exceed limit, it is fully skipped.
2. No partial text for that node appears in `node_texts`.
3. The returned set contains only fully included nodes.

=========================

Review Notes on Test Completeness 2026-02-05

The items below summarize **all not fully covered or missing** behaviors from `retrieval_contract_coverage.md`. Each item includes a proposed **integration test** and the **expected result** (grounded in the Fake Enterprise 1.0/1.1 bundles).

1) Gap: `search_nodes` must not materialize text or write `context_blocks` (partial coverage)
Proposed integration test:
- Add a case that runs **only** `SearchNodesAction` (without `fetch_node_texts`) using an existing query from the fake dataset, e.g. “Where is the application entry point and bootstrap?”.
Expected result:
- `state.retrieval_seed_nodes` is non-empty.
- `state.node_texts` is empty.
- `state.context_blocks` is empty.

2) Gap: Fail-fast when `repository` or `snapshot_id` is missing (not covered)
Proposed integration test:
- Build a minimal pipeline run that calls `search_nodes` with `state.repository=""` or `state.snapshot_id=""` and the Fake repository (“Fake”) context.
Expected result:
- The action raises a runtime error before any retrieval is executed.

3) Gap: `top_k` must be provided by step or settings (not covered)
Proposed integration test:
- Run `search_nodes` without `top_k` and without `pipeline_settings["top_k"]`.
Expected result:
- Runtime error indicating missing `top_k`.

4) Gap: Rerank only allowed for `semantic`; fail-fast for `bm25`/`hybrid` (not covered)
Proposed integration test:
- Execute `search_nodes` with `search_type=bm25` (or `hybrid`) and `rerank=keyword_rerank`.
Expected result:
- Runtime error.

5) Gap: Sacred `retrieval_filters` cannot be overridden by parsing (partial coverage)
Proposed integration test:
- Provide `state.retrieval_filters` with `acl_tags_any=["finance"]`, then use a query payload that tries to override ACL (e.g., empty or different groups).
Expected result:
- Applied filters still include the original ACL; returned docs respect `finance` ACL.

6) Gap: `graph_max_depth` and `graph_max_nodes` are enforced (partial coverage)
Proposed integration test:
- Run dependency expansion with `graph_max_depth=1` and `graph_max_nodes=2` using the seed `SQL:dbo.proc_ProcessPayment`.
Expected result:
- Expanded nodes do not exceed depth 1.
- Total expanded nodes <= 2.

7) Gap: Fail-fast when graph settings mapping (`*_from_settings`) is missing (not covered)
Proposed integration test:
- Execute `expand_dependency_tree` with missing `max_depth_from_settings` or missing key in settings.
Expected result:
- Runtime error before graph expansion.

8) Gap: `graph_debug` minimal schema is required (partial coverage)
Proposed integration test:
- After `expand_dependency_tree`, assert `graph_debug` has keys: `seed_count`, `expanded_count`, `edges_count`, `truncated`, `reason`.
Expected result:
- All keys present with valid types.

9) Gap: Security trimming in `expand_dependency_tree` (not covered)
Proposed integration test:
- Run expansion with `acl_tags_any=["finance","security"]` and `classification_labels_all=["restricted"]`.
Expected result:
- Expanded nodes and edges exclude any node failing ACL or classification.
- Example exclusions in Fake bundles: nodes like `C0027` or `C0003` if tagged outside ACL (as described in section 6).

10) Gap: `node_texts` minimal schema (`id`, `text`, `is_seed`, `depth`, `parent_id`) (partial coverage)
Proposed integration test:
- After `fetch_node_texts`, validate schema for each item.
Expected result:
- All fields present and consistent (seeds have `depth=0`, `parent_id=None`).

11) Gap: Mutual exclusivity of `budget_tokens` and `max_chars` (not covered)
Proposed integration test:
- Run `fetch_node_texts` with both `budget_tokens` and `max_chars` set.
Expected result:
- Runtime error before any materialization.

12) Gap: Fail-fast for missing `max_context_tokens` or non-positive values (not covered)
Proposed integration test:
- Execute `fetch_node_texts` with `pipeline_settings.max_context_tokens <= 0`.
Expected result:
- Runtime error indicating invalid budget source.

13) Gap: Hybrid RRF algorithm (dedup + tie-breaks) (not covered)
Proposed integration test:
- Use controlled retrieval results to force RRF ties, then run a hybrid query.
Expected result:
- Ordering respects `score → semantic_rank → bm25_rank → ID`.

14) Gap: SnapshotSet resolution and conflicts (not covered)
Proposed integration test:
- Build a case that sets only `snapshot_set_id=Fake_snapshot` and confirms it resolves to a concrete snapshot.
- Build a conflicting case (`snapshot_id` from release-1.0 vs `snapshot_set_id` resolving to release-1.1).
Expected result:
- Resolution is deterministic:
  - Release 1.0 snapshot: `fdb0d25c05c0b1647d4954a0f1850aff13570970`
  - Release 1.1 snapshot: `0edca56531e955968794aafa95b082a4badf26b9`
- Conflicts trigger fail-fast.

15) Gap: Reranking with `widen_factor` (not covered)
Proposed integration test:
- `semantic + keyword_rerank` with `top_k=5` and `widen_factor=6`.
Expected result:
- Backend retrieval is called with `top_k=30`, reranker returns only top 5.

16) Gap: `fetch_node_texts` edge cases (not covered)
Proposed integration test:
- Case A: IDs valid but missing text in backend.
- Case B: all candidate nodes exceed budget individually.
- Case C: large number of seed nodes + very small budget.
Expected result:
- Case A: missing text nodes are skipped or returned empty consistently.
- Case B: `node_texts == []`.
- Case C: deterministic subset based on prioritization order.

17) Gap: Empty or degenerate inputs for `expand_dependency_tree` (not covered)
Proposed integration test:
- Run expansion with empty `retrieval_seed_nodes`.
Expected result:
- No nodes/edges returned; `graph_debug.reason == "no_seeds"` (or equivalent).

18) Gap: Backend abstraction (no direct FAISS usage) (not covered)
Proposed integration test:
- Run `search_nodes`/`fetch_node_texts` with a stub backend and assert the actions use `runtime.retrieval_backend` calls.
Expected result:
- All retrieval operations go through the injected backend; no direct FAISS access.

19) Gap: Unknown `search_type` must fail-fast (not covered)
Proposed integration test:
- Execute `search_nodes` with `search_type="fuzzy"` (or a typo like `semantc`).
Expected result:
- Runtime error indicating unsupported search mode.

20) Gap: Merge rules for `retrieval_filters` vs `parsed_filters` (not covered)
Proposed integration test:
- Provide `state.retrieval_filters` with ACL/classification, then pass a query payload that tries to override them (e.g., empty or conflicting ACL).
Expected result:
- Final applied filters still include the original ACL/classification; parser can only add non-security filters.

21) Gap: `codebert_rerank` is reserved and must fail-fast (not covered)
Proposed integration test:
- Execute `search_nodes` with `search_type="semantic"` and `rerank="codebert_rerank"`.
Expected result:
- Runtime error indicating the reranker is not available/reserved.

22) Gap: Explicit conflict between `snapshot_id` and `snapshot_set_id` (not covered)
Proposed integration test:
- Set `snapshot_id` to release 1.0 (`fdb0d25c05c0b1647d4954a0f1850aff13570970`) and `snapshot_set_id=Fake_snapshot` resolved to release 1.1.
Expected result:
- Runtime error due to conflicting snapshot scope.

23) Gap: Very large `top_k` with tiny token budget in `fetch_node_texts` (not covered)
Proposed integration test:
- Use `top_k=100` in search, but set `budget_tokens` to allow only 2–3 nodes in fetch.
Expected result:
- Deterministic truncation to the smallest set that fits the budget (consistent ordering with prioritization mode).

24) Gap: Empty query in `search_nodes` must fail-fast (not covered)
Proposed integration test:
- Execute `search_nodes` with an empty query (after parsing/normalization).
Expected result:
- Runtime error indicating empty/invalid query.

25) Gap: Unknown `rerank` value must fail-fast (not covered)
Proposed integration test:
- Execute `search_nodes` with `search_type="semantic"` and `rerank="foo_rerank"`.
Expected result:
- Runtime error indicating unsupported rerank option.

Note after running integration tests (2026-02-05):
- Check results in `log/integration/retrival/test_results_latest.log`.
- These logs are not committed to the repository, so each run must generate them locally and review them.

=========================

Additional ACL + Classification Tests (English, numbered)

Shared assumptions:
User ACL: `["finance", "security"]`.
User classification: `["public", "internal", "secret"]`.
ACL = OR, Classification = ALL/subset, empty ACL = public and allowed.
Data source:
- Use the fake bundles imported by integration tests: `tests/repositories/fake/Release_FAKE_ENTERPRISE_1.0.zip` and `Release_FAKE_ENTERPRISE_1.1.zip`.
- Node metadata comes from those bundles (fields `acl_allow` and `classification_labels`).
- Test selection rule: pick concrete node IDs or source files from the fake bundles that match each ACL/classification combination.
Data preparation method (how we guarantee tag combinations):
- During test setup, query Weaviate directly to select candidate nodes by metadata filters.
- For each ACL/classification combination, run a metadata-only query (no vector search) and store the resulting node IDs in the test fixture.
- If a combination returns zero nodes, the test should explicitly fail with a clear message (data coverage gap), not silently skip.

How to obtain nodes for each combination:
- ACL = public: filter `acl_allow` is empty (`[]`) AND no classification constraint.
- ACL contains `finance`: filter `acl_allow` contains_any `["finance"]`.
- ACL contains `security`: filter `acl_allow` contains_any `["security"]`.
- ACL contains `hr` only (negative): filter `acl_allow` contains_any `["hr"]` AND NOT contains_any `["finance","security"]`.
- Classification subset: filter `classification_labels` contains_all `["public"]` or `["internal","secret"]`.
- Classification negative: filter `classification_labels` contains_any `["restricted"]` AND NOT contains_all `["public","internal","secret"]`.

How to expand dependency tree with controlled tags:
- Select seed nodes using the metadata filters above (ACL/classification combinations).
- Use `expand_dependency_tree` with those seed IDs and `retrieval_filters` set to the user ACL/classification.
- Validate expansion results by re-querying metadata for all returned node IDs and checking ACL/classification compliance.

Tests for `search_nodes` + `fetch_node_texts`
1. Test S1 (search_nodes): Doc ACL `[]`, classification `[]`. Data prep: select a node with empty `acl_allow` and empty `classification_labels`. Expected: document is returned (public).
2. Test S2 (search_nodes): Doc ACL `["finance"]`, classification `[]`. Data prep: select a node where `acl_allow` contains `finance` and `classification_labels` empty. Expected: document is returned.
3. Test S3 (search_nodes): Doc ACL `["security"]`, classification `[]`. Data prep: select a node where `acl_allow` contains `security` and `classification_labels` empty. Expected: document is returned.
4. Test S4 (search_nodes): Doc ACL `["finance","security"]`, classification `[]`. Data prep: select a node where `acl_allow` contains both `finance` and `security`. Expected: document is returned.
5. Test S5 (search_nodes): Doc ACL `["hr"]`, classification `[]`. Data prep: select a node where `acl_allow` contains `hr` and does not contain `finance` or `security`. Expected: document is not returned.
6. Test S6 (search_nodes): Doc ACL `["finance","hr"]`, classification `[]`. Data prep: select a node where `acl_allow` contains `finance` and `hr`. Expected: document is returned (match on `finance`).
7. Test S7 (search_nodes): Doc ACL `[]`, classification `["public"]`. Data prep: select a node with empty `acl_allow` and `classification_labels` contains `public`. Expected: document is returned.
8. Test S8 (search_nodes): Doc ACL `[]`, classification `["internal","secret"]`. Data prep: select a node with empty `acl_allow` and `classification_labels` contains `internal` and `secret`. Expected: document is returned.
9. Test S9 (search_nodes): Doc ACL `[]`, classification `["public","internal","secret"]`. Data prep: select a node with empty `acl_allow` and `classification_labels` contains all three labels. Expected: document is returned.
10. Test S10 (search_nodes): Doc ACL `[]`, classification `["public","secret","restricted"]`. Data prep: select a node whose `classification_labels` includes `restricted`. Expected: document is not returned.
11. Test S11 (search_nodes): Doc ACL `["finance"]`, classification `["internal"]`. Data prep: select a node with `acl_allow` contains `finance` and `classification_labels` contains `internal`. Expected: document is returned.
12. Test S12 (search_nodes): Doc ACL `["security"]`, classification `[]`. Data prep: select a node with `acl_allow` contains `security` and empty classification. Expected: document is returned.
13. Test S13 (search_nodes): Doc ACL `["hr"]`, classification `["public"]`. Data prep: select a node with `acl_allow` contains `hr` and `classification_labels` contains `public` but not `finance/security`. Expected: document is not returned (ACL fail).
14. Test S14 (search_nodes): Doc ACL `["finance"]`, classification `["restricted"]`. Data prep: select a node with `acl_allow` contains `finance` and `classification_labels` includes `restricted`. Expected: document is not returned (classification fail).
15. Test S15 (search_nodes): Doc ACL `["finance","hr"]`, classification `["internal","secret"]`. Data prep: select a node with `acl_allow` contains `finance` and `hr`, and `classification_labels` contains `internal` and `secret`. Expected: document is returned.
16. Test S16 (fetch_node_texts): Search results include docs with ACL `[]` and `["finance"]`. Data prep: select one public node and one finance-tagged node, run search to retrieve both. Expected: texts for both are materialized.
17. Test S17 (fetch_node_texts): Search results include a doc with classification `["restricted"]`. Data prep: include one restricted node in candidate list, run search with classification filter. Expected: that doc is not present in `node_texts`.

Tests for `expand_dependency_tree`
1. Test E1 (expand_dependency_tree): Seed ACL `[]`, classification `[]`. Data prep: pick a public seed node (empty ACL and empty classification). Expected: expansion returns only compliant nodes.
2. Test E2 (expand_dependency_tree): Seed ACL `["finance"]`, classification `[]`. Data prep: pick a seed node with `acl_allow` contains `finance`. Expected: expanded nodes are public or contain `finance`.
3. Test E3 (expand_dependency_tree): Seed ACL `["hr"]`, classification `[]`. Data prep: pick a seed node with `acl_allow` contains `hr` and not `finance/security`. Expected: no nodes/edges returned (ACL fail).
4. Test E4 (expand_dependency_tree): Seed ACL `[]`, classification `["public"]`. Data prep: pick a seed node with empty ACL and classification containing `public`. Expected: only nodes whose classification is a subset of `["public","internal","secret"]`.
5. Test E5 (expand_dependency_tree): Seed ACL `[]`, classification `["restricted"]`. Data prep: pick a seed node with classification containing `restricted`. Expected: no nodes/edges returned (classification fail).
6. Test E6 (expand_dependency_tree): Seed ACL `["finance"]`, classification `["internal"]`. Data prep: pick a seed node with ACL contains `finance` and classification contains `internal`. Expected: only nodes satisfying both conditions.
7. Test E7 (expand_dependency_tree): Seed ACL `["security"]`, classification `[]`. Data prep: pick a seed node with ACL contains `security`. Expected: public nodes and `security` nodes are returned.
8. Test E8 (expand_dependency_tree): Seed ACL `["finance"]`, classification `["restricted"]`. Data prep: pick a seed node with ACL contains `finance` and classification contains `restricted`. Expected: no nodes/edges returned (classification fail).
9. Test E9 (expand_dependency_tree): Seed ACL `[]`, classification `[]` with graph nodes having ACL `["hr"]`. Data prep: ensure graph contains at least one `hr` node reachable from seed. Expected: `["hr"]` nodes are trimmed.
10. Test E10 (expand_dependency_tree): Seed ACL `[]`, classification `[]` with graph nodes having classification `["restricted"]`. Data prep: ensure graph contains at least one `restricted` node reachable from seed. Expected: `["restricted"]` nodes are trimmed.
