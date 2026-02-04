# Retrieval Integration Test Expectations (Fake Snapshot)

This document defines **expected outcomes** for the integration suite under:
- `tests/integration/retrival/test_fake_snapshot_bootstrap.py`
- `tests/integration/retrival/test_search_and_fetch_expectations.py`

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
  - ~10% `classification_level`
  - ~5% both `acl_tags_any` and `classification_level`

## Run Command
From repository root:

```bash
conda activate rag-faiss2
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

## 5) Security Filter Scenarios (`acl_tags_any` + `classification_labels_all`)

This section defines expected behavior when security filters are present in `retrieval_filters`.

### Security Logic Contract
1. `acl_tags_any` is evaluated as OR.
2. `classification_labels_all` is evaluated as AND.
3. If both are present, effective rule is:
   - `(document.acl intersects user.acl_tags_any)` AND `(all document.classification labels are allowed)`
4. Empty document classifications are allowed by default.
5. `owner_id` is reserved for future use and is not enforced in current integration checks.

### Expected Trace Fields
When security scenarios are executed, `state_after.retrieval_filters` should include:
1. `repo`
2. `snapshot_id` (or `snapshot_ids_any`)
3. `acl_tags_any` (if ACL scenario is active)
4. `classification_labels_all` (if classification scenario is active)

Example:

```json
{
  "repo": "Fake",
  "snapshot_id": "<resolved_snapshot_id>",
  "acl_tags_any": ["finance", "security"],
  "classification_labels_all": ["internal", "sensitive"]
}
```

### Expected Behavior Matrix

#### ACL-only scenario
User groups: `["finance", "security"]`
Expected:
1. Documents tagged with `finance` are visible.
2. Documents tagged with `security` are visible.
3. Documents tagged with `hr` only are not visible.

#### Classification-only scenario
User classification set: `["public", "internal", "secret"]`
Expected:
1. Document labels `[]` -> visible.
2. Document labels `["public"]` -> visible.
3. Document labels `["secret"]` -> visible.
4. Document labels `["internal", "secret"]` -> visible.
5. Document labels `["sensitive"]` -> not visible.

#### ACL + classification scenario
User ACL: `["finance", "security"]`
User classification: `["public", "internal", "secret"]`
Expected:
1. Doc ACL `["finance"]`, class `["internal"]` -> visible.
2. Doc ACL `["security"]`, class `[]` -> visible.
3. Doc ACL `["hr"]`, class `["internal"]` -> not visible (ACL fail).
4. Doc ACL `["finance"]`, class `["sensitive"]` -> not visible (classification fail).

### Result Interpretation in Logs
For security cases, compare:
1. `retrieval_filters` in pipeline trace (`log/integration/retrival/pipeline_traces/*.json`).
2. `Observed results` in `log/integration/retrival/test_results_latest.log`.
3. Presence/absence of expected sources for each scenario.

Security tests pass when:
1. The expected filter fields are present in trace.
2. Allowed documents are retrievable.
3. Disallowed documents are consistently excluded.
4. `Observed security` in `test_results_latest.log` confirms ACL/classification metadata for returned documents.

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

#### A) Full allowlist (default)
Allowed relations:
- `ReadsFrom`, `WritesTo`, `Calls`, `Executes`, `FK`, `On`, `SynonymFor`, `ReferencedBy(C#)`

Expected nodes:
1. `SQL:dbo.proc_ProcessPayment` (seed)
2. `SQL:dbo.table_Payments`
3. `SQL:dbo.proc_ValidateToken`
4. `SQL:dbo.proc_ComputeFraudRisk`
5. `SQL:dbo.table_Tokens`
6. `SQL:dbo.table_AclRecords`

Expected edges:
1. `SQL:dbo.proc_ProcessPayment` --`WritesTo`--> `SQL:dbo.table_Payments`
2. `SQL:dbo.proc_ProcessPayment` --`Executes`--> `SQL:dbo.proc_ValidateToken`
3. `SQL:dbo.proc_ProcessPayment` --`Executes`--> `SQL:dbo.proc_ComputeFraudRisk`
4. `SQL:dbo.proc_ValidateToken` --`ReadsFrom`--> `SQL:dbo.table_Tokens`
5. `SQL:dbo.proc_ComputeFraudRisk` --`ReadsFrom`--> `SQL:dbo.table_Payments`
6. `SQL:dbo.proc_ComputeFraudRisk` --`ReadsFrom`--> `SQL:dbo.table_AclRecords`

#### B) Limited allowlist (ReadsFrom / WritesTo / Calls)
Allowed relations:
- `ReadsFrom`, `WritesTo`, `Calls`

Expected nodes:
1. `SQL:dbo.proc_ProcessPayment` (seed)
2. `SQL:dbo.table_Payments`

Expected edges:
1. `SQL:dbo.proc_ProcessPayment` --`WritesTo`--> `SQL:dbo.table_Payments`

#### C) Write-only allowlist (WritesTo)
Allowed relations:
- `WritesTo`

Expected nodes:
1. `SQL:dbo.proc_ProcessPayment` (seed)
2. `SQL:dbo.table_Payments`

Expected edges:
1. `SQL:dbo.proc_ProcessPayment` --`WritesTo`--> `SQL:dbo.table_Payments`

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
