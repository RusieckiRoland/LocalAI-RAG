# ADR-0004: Replace FAISS-based retrieval with Weaviate

- **Status:** Accepted  
- **Date:** 2026-02-01  
- **Decision maker:** Roland (architecture owner for LocalAI-RAG / Indexer)  
- **Related:** ADR-0001 (Canonical node identity as graph seed), ADR-0002 (Design by Contract for YAML pipelines), ADR-0003 (Retrieval Model and Multi-Stage Retrieval Pipeline)

## Context

LocalAI-RAG uses a contract-driven, multi-stage retrieval pipeline:

```
search_nodes → expand_dependency_tree → fetch_node_texts
```

This architecture is explicitly designed to be deterministic, auditable, and safe with respect to access control filters (ACL) and other metadata filters.

Until now, the retrieval backend has been implemented around FAISS for vector search, with additional capabilities (BM25, hybrid search, metadata filtering, ACL enforcement) implemented in custom code.

In practice, meeting all project requirements with a FAISS-centric stack has required increasing amounts of bespoke infrastructure:
- maintaining separate stores for text + metadata,
- implementing BM25, hybrid fusion, and reranking orchestration manually,
- enforcing “filters before ranking/truncation” across all retrieval modes,
- keeping behavior deterministic and testable under the Design-by-Contract constraints.

This has caused the retrieval layer to become disproportionately complex compared to its business value.

## Decision

We **fully discontinue** the FAISS-based retrieval/index solution and migrate the retrieval backend and document store to **Weaviate**.

**Rationale:**
- Weaviate provides **native** support for the retrieval modes we currently implement manually:
  - vector (semantic) search,
  - BM25 search,
  - hybrid search (BM25 + vector),
  - metadata filtering (including ACL-style filters).
- Continuing to evolve a FAISS-centric backend would keep adding custom code paths, increasing complexity and long-term maintenance costs, without delivering proportional product value.

## Key principles preserved (non-negotiable)

The migration to Weaviate **does not change** the architectural contracts established by previous ADRs:

1) **Canonical IDs remain the join key.**  
   Retrieval results must map to canonical indexer IDs (chunk_id/node_key), which seed graph expansion.

2) **Design by Contract remains enforced.**  
   Actions keep explicit Requires/Ensures; invalid pipelines fail fast with actionable errors.

3) **Multi-stage retrieval remains intact.**  
   - `search_nodes` outputs seed IDs only, never text.
   - `expand_dependency_tree` expands IDs/edges, not text.
   - `fetch_node_texts` materializes text with explicit budgeting.

4) **ACL / metadata filtering remains mandatory in every stage.**  
   Each retrieval-related action MUST enforce the same filters independently.

## Alternatives considered

### Option A: Keep FAISS and continue extending custom retrieval (rejected)
- **Rejected** due to high engineering overhead and growing complexity:
  - manual BM25 + hybrid fusion,
  - duplicated indexing and storage concerns,
  - increased surface area for subtle “filtering vs truncation” bugs,
  - higher maintenance burden and slower iteration.

### Option B: Defer Weaviate to Stage III metrics phase (rejected)
ADR-0003 previously treated Weaviate as a future consideration.  
We initially planned to introduce Weaviate in **Stage III**, where metric collection and benchmarking were planned.

This plan is updated:
- The **engineering cost** of maintaining and evolving the FAISS-centric backend has become the dominant risk.
- Migrating earlier reduces code complexity and stabilizes the retrieval layer sooner, which improves the quality and reliability of the metric phase (because less custom retrieval code must be validated).

### Option C: Use another vector database backend (deferred)
Other vector databases may be evaluated later, but Weaviate is selected now because it directly covers the required retrieval modes and filtering semantics with minimal custom code.

## Consequences

### Pros
- Major reduction in custom retrieval code (BM25/hybrid/filtering/doc-store glue).
- Unified backend for vector search + BM25 + hybrid search + metadata filtering.
- Faster iteration on retrieval behavior while preserving pipeline contracts.
- Clearer operational boundary: `runtime.retrieval_backend` becomes “the only door” to retrieval.

### Cons / costs
- Operational dependency on a database service (deployment, persistence, upgrades).
- Migration work:
  - schema/collection design,
  - import pipeline for texts + metadata (+ optionally vectors),
  - test suite updates to validate Weaviate behavior, especially around filtering and determinism.
- Need to ensure that security invariants (“filters before ranking/truncation”) are enforced consistently across modes.

## Implementation notes (non-normative)

- **Graph traversal remains a separate concern.**  
  Weaviate is used for retrieval + filtering + text/metadata storage; dependency graph expansion remains driven by the existing graph provider, seeded by canonical IDs.

- **Metrics phase becomes more meaningful.**  
  With less bespoke retrieval plumbing, Stage III metrics can focus on retrieval quality and system behavior rather than validating custom indexing mechanics.

## Summary

We retire the FAISS-based retrieval/index approach and adopt Weaviate as the retrieval backend and document store. This eliminates unnecessary custom complexity while preserving the contract-driven, multi-stage retrieval architecture and the canonical-ID graph seeding model defined by prior ADRs.
