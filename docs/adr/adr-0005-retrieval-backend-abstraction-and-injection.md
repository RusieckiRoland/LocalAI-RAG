# ADR-0005: Pluggable Retrieval Backend via `IRetrievalBackend` (Weaviate default)

- **Status:** Accepted  
- **Date:** 2026-02-02  
- **Decision maker:** Roland (architecture owner for LocalAI-RAG)  
- **Related:** ADR-0002 (Design by Contract for YAML pipelines), ADR-0003 (Retrieval model), ADR-0004 (FAISS → Weaviate)

## Context

LocalAI-RAG uses a contract-driven, multi-stage retrieval pipeline:

```
search_nodes → expand_dependency_tree → fetch_node_texts
```

The system must remain:
- deterministic and auditable,
- safe w.r.t. ACL / metadata filters,
- maintainable without repeatedly refactoring actions when the underlying search technology changes.

We selected **Weaviate** as the current retrieval backend (ADR-0004). However, we also want the freedom to switch to another backend (e.g., Qdrant) later without rewriting pipeline actions or changing the retrieval contracts.

## Decision

1) **Pipeline actions MUST depend only on the stable port:** `IRetrievalBackend`  
   - Actions access retrieval exclusively via `runtime.get_retrieval_backend()`.
   - No action may directly import or reference vendor-specific clients (Weaviate/Qdrant/etc.).

2) **Backend selection is performed in exactly one place (composition root):** a small **factory** that creates the concrete backend implementation from configuration (config/env).  
   - Weaviate is the **default** implementation.
   - Future backends (e.g., Qdrant) are additional implementations behind the same port.

3) **The retrieval contract remains strict and fail-fast:**  
   - If a pipeline step requires retrieval and the backend is not configured, execution MUST fail with an actionable error.

## Non-negotiable invariants

These are mandatory for every retrieval mode and every stage:

1) **Filters are applied BEFORE ranking/top-k/fusion/truncation.**  
   The candidate set must be narrowed by filters first; only then can scoring and top-k selection happen.

2) **Canonical IDs are the join key.**  
   Retrieval results must map to canonical node IDs used as seeds for graph expansion.

3) **Stage responsibilities remain unchanged.**
   - `search_nodes` returns seed IDs (and minimal metadata), not full text.
   - `expand_dependency_tree` expands IDs/edges using the graph provider, not the vector DB.
   - `fetch_node_texts` materializes text with explicit budgeting and filters.

4) **ACL / metadata filters are enforced independently in each stage.**  
   No stage assumes “previous stage already filtered correctly”. Each stage re-applies the same filter rules.

## Implementation notes (normative)

### Ports (stable interfaces)
- `IRetrievalBackend` is the single retrieval entrypoint used by the pipeline.
- `IGraphProvider` remains the single entrypoint for dependency graph traversal.
- `ITokenCounter`, `IHistoryManager`, `IModelClient`, etc. remain independent ports as defined by the pipeline architecture.

### Composition root / factory (single selection point)
- The application creates `IRetrievalBackend` using a factory driven by configuration, e.g.:
  - `retrieval_backend: weaviate | qdrant | ...`
  - `weaviate: { url, api_key, collection, ... }`
  - `qdrant:   { url, api_key, collection, ... }`
- Only the factory knows vendor-specific details.
- The rest of the system remains vendor-agnostic.

### Legacy compatibility
- Any legacy “dispatcher” objects are considered transitional.
- Actions must not rely on them. Tests may still use fakes/stubs, but the public contract is `IRetrievalBackend`.

## Alternatives considered

### A) Hard-code Weaviate everywhere (rejected)
- Would force future refactors across multiple actions and tests.
- Increases coupling and makes the system brittle.

### B) Keep multiple backends active in parallel in actions (rejected)
- Encourages conditional logic inside actions and complicates contracts.
- Makes correctness (especially filtering-before-ranking) harder to audit.

### C) Plugin system with dynamic imports everywhere (rejected)
- Too much dynamism; increases the chance of hidden runtime failures.
- Contradicts “fail-fast, explicit contract” goals.

## Consequences

### Pros
- Switching retrieval backends becomes a **composition-only** change (factory/config), not an action rewrite.
- The “filters before ranking/top-k/fusion” rule stays centralized and testable at the backend boundary.
- Tests can use a single fake backend for deterministic scenarios.

### Cons
- Requires discipline: no vendor-specific shortcuts in actions.
- The factory becomes a critical integration point (must be covered by tests).

## Migration / verification plan

1) Ensure all retrieval-using actions call only `runtime.get_retrieval_backend()`.
2) Provide a Weaviate-backed implementation as the default.
3) Add a lightweight in-memory fake backend for tests.
4) Keep (or add) hard-proof tests for:
   - “filters BEFORE top-k” across retrieval modes,
   - deterministic ordering and stable IDs,
   - fail-fast errors when backend is missing.

## Summary

Retrieval is standardized behind `IRetrievalBackend`, and the concrete backend (Weaviate today, others later) is selected only in a single composition root factory. This preserves strict contracts, enforces pre-filtering before ranking/truncation, and prevents future backend migrations from forcing action rewrites.
