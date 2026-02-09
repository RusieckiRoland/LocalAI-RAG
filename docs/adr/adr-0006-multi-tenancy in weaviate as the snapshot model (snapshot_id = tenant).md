# ADR-0006: Multi-tenancy in Weaviate via `snapshot_id` (tenant) and `snapshot_set` (comparison set)

- **Status:** Accepted  
- **Date:** 2026-02-09  
- **Decision maker:** Roland (architecture owner for LocalAI-RAG)  
- **Related:** ADR-0001 (Canonical node identity), ADR-0003 (Retrieval model), ADR-0004 (FAISS → Weaviate), ADR-0005 (Retrieval backend abstraction)

## Context

LocalAI-RAG stores multiple **code snapshots** in a single Weaviate instance to support:
- deterministic retrieval for a specific code state,
- parallel work on multiple repositories/branches,
- integration tests that compare behavior across snapshots,
- cheap cleanup of test data.

We use Weaviate collections `RagNode` and `RagEdge` as the storage for:
- node metadata (canonical_id, source_file, etc.),
- embeddings / chunk vectors,
- graph edges used by dependency expansion.

Without isolation, data from different snapshots would mix and cause:
- non-deterministic retrieval results,
- accidental cross-snapshot leakage during graph expansion,
- harder cleanup (delete-by-filter instead of drop-by-scope),
- unclear test reproducibility.

## Definitions (normative)

### `snapshot_id`
`snapshot_id` is the **single source of truth** for the code snapshot identity.

It is also the **Weaviate tenant name**.

`snapshot_id` is built deterministically:
- **Git repositories:** `UUID(repoName:HeadSha)`  
- **Non-Git repositories:** `UUID(repoName:folderFingerprint)`  

Where:
- `repoName` is the stable configured repository name,
- `HeadSha` is the commit SHA of the imported snapshot,
- `folderFingerprint` is a content hash (a digest computed from *all project files*) representing the exact folder state.

> Note: The exact UUID construction must remain deterministic for the same inputs. The goal is stable, collision-resistant snapshot identity, not human readability.

### `snapshot_set`
A `snapshot_set` is a **set of tenants (`snapshot_id`s)** that represent one **comparison material**.

Typical use:
- Compare two repositories / two branches / two states in one integration run.
- The test runner executes the same query **once per tenant** (per `snapshot_id`) under a single `snapshot_set_id`.

A `snapshot_set` is not a tenant. It is an orchestration concept used by the test harness / pipeline runner.

## Decision

1) **Enable multi-tenancy** for Weaviate collections used by retrieval:
   - `RagNode`: multi-tenant
   - `RagEdge`: multi-tenant

2) **Treat `snapshot_id` as the tenant identifier** everywhere:
   - import writes objects into the tenant = `snapshot_id`,
   - every query MUST include the tenant,
   - cross-tenant queries are forbidden by default.

3) **Treat `snapshot_set_id` as a list of tenants** (resolved before querying):
   - `snapshot_set_id` resolves to `snapshot_id[]`,
   - integration tests loop over those tenants and compare results deterministically.

4) **Fail fast when tenant is missing**:
   - if a code path attempts to query multi-tenant collections without specifying tenant, execution MUST fail with an actionable error,
   - no “fallback to default tenant” is allowed.

## Non-negotiable invariants

1) **Determinism**
- The same `(snapshot_id, query, filters, pipeline config)` must produce stable results (within known embedding/search non-determinism limits).

2) **Isolation**
- Retrieval, graph expansion, and fetch MUST not mix data across snapshots.

3) **Filter ordering**
- All ACL / metadata filters are applied **before** ranking/top-k/fusion in every stage (per ADR-0005).

4) **No silent fallback**
- Missing tenant is a hard error. We do not mask bugs by continuing in an implicit “default scope”.

## Implementation notes (normative)

### Weaviate schema / collections
- Collections used by retrieval MUST be created with multi-tenancy enabled.
- Tenant creation must happen as part of snapshot import/bootstrap for `snapshot_id`.

### Client / query execution
- Every `fetch_objects`, `near_text`, `bm25`, `hybrid`, or gRPC query must specify tenant = `snapshot_id`.
- Helper functions used by integration tests that load observed docs/sources MUST query within the same tenant.

### Pipeline inputs
- Pipeline runtime MUST carry `snapshot_id` (tenant) as a first-class value.
- `snapshot_set_id` is allowed only at orchestration level; it must resolve to tenant list before issuing retrieval queries.

## Alternatives considered

1) **Single-tenant (no multi-tenancy) + strict filtering by snapshot_id metadata**
- Pros: simpler schema (no tenants).
- Cons: higher risk of cross-snapshot leakage, heavier deletes, more complex correctness proofs, higher blast radius for bugs.

2) **Separate Weaviate instance per snapshot**
- Pros: very strong isolation.
- Cons: operationally expensive; slower tests; complicated orchestration; not scalable for many snapshots.

3) **Separate Weaviate collection per snapshot**
- Pros: isolation at collection level.
- Cons: schema proliferation; management overhead; still harder to do consistent tooling and test harness.

We choose multi-tenancy because it provides strong isolation with manageable operational complexity.

## Consequences

### Positive
- Strong snapshot isolation and reproducibility.
- Cleaner test environments: easy tenant-level cleanup.
- Explicit “tenant required” errors reveal missing-scoping bugs early.

### Negative / costs
- Every code path touching Weaviate must be tenant-aware.
- Bootstrapping must ensure tenants exist before queries.
- Some Weaviate APIs behave differently when multi-tenancy is enabled (tenant is mandatory).

## Rollout / migration

- Step 1: Enable multi-tenancy on required collections (fresh IT containers).
- Step 2: Update importer to write into tenant = `snapshot_id` and create tenants on import.
- Step 3: Update retrieval backend + integration helpers to always include tenant.
- Step 4: Add/adjust integration tests to catch “missing tenant” regressions.

## Open questions

- Tenant cleanup strategy for long-running local instances (policy, retention, tooling).
- Maximum supported tenant count and operational thresholds for our workload (measure and document with real metrics).
