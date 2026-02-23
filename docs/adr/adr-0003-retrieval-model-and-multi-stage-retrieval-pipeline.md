# ADR-0003: Retrieval Model and Multi-Stage Retrieval Pipeline

- **Status:** Proposed
- **Date:** 2026-01-15
- **Decision maker:** Roland (architecture owner for LocalAI-RAG / Indexer)
- **Related:** ADR-0001 (Canonical node identity for graph-augmented retrieval), ADR-0002 (Design by Contract for YAML pipelines)

## Context

LocalAI-RAG uses YAML-defined, CI/CD-like pipelines composed of small, deterministic actions.
As the system evolves toward graph-augmented retrieval, it becomes critical to clearly define
the **retrieval model** and the **responsibilities and contracts** of the retrieval-related actions.

In particular, we want to formalize how the following actions cooperate:

```
search_nodes → expand_dependency_tree → fetch_node_texts
```

The goal is to ensure:
- deterministic behavior,
- strict separation of responsibilities,
- consistent access-control enforcement,
- and scalability of the retrieval layer.

## Decision

We adopt a **three-stage retrieval model** with explicit contracts:

### 1. `search_nodes` — Retrieval / Candidate Selection

**Responsibility**
- Perform information retrieval using one of the supported modes:
  - `semantic`
  - `bm25`
  - `hybrid`

**Reranking**
- The action *may* internally apply a reranking phase (e.g. using CodeBERT or another cross-encoder).
- Reranking is considered an **internal implementation detail** of retrieval.
- It does not affect the external contract of the action.

**Contract**
- **Ensures:** the action always outputs **only canonical node/chunk IDs** (`retrieval_seed_nodes`).
- Text content may be accessed internally for ranking purposes, but is **never exposed** as a pipeline artifact.

This guarantees that downstream steps do not accidentally depend on textual payloads
and that token budgets remain fully controlled.

### 2. `expand_dependency_tree` — Graph Expansion

**Responsibility**
- Expand a dependency graph starting from the seed node IDs produced by `search_nodes`.
- Traverse the graph according to configured constraints (depth, node limits, edge allowlist).

**Contract**
- **Requires:** a non-empty set of seed node IDs.
- **Ensures:** a set of expanded node IDs and dependency edges.

This step operates strictly on **identities and relationships**, never on text.

### 3. `fetch_node_texts` — Text Materialization

**Responsibility**
- Fetch textual content for nodes selected by the graph expansion stage.
- Enforce explicit size limits and budgeting (e.g. `max_chars`).

**Contract**
- **Requires:** graph-expanded node IDs (or seed nodes as a fallback).
- **Ensures:** textual payloads (`node_texts`) ready for prompt construction.

Text is materialized **only at this stage**, ensuring predictable cost and context size.

## Access Control and Security Invariants

If access-control filters are defined (e.g. repository, branch, tenant, permissions, user rights):

- **Every retrieval-related action MUST apply these filters independently**, including:
  - `search_nodes`
  - `expand_dependency_tree`
  - `fetch_node_texts`

This prevents security leaks such as:
- `search_nodes` respecting user permissions,
- while `expand_dependency_tree`, operating on the dependency graph, expands into nodes
  the user is not authorized to access.

Access control is therefore a **mandatory invariant**, not an implicit assumption.

## Future Considerations: Vector Database Backend

We are considering a future migration from FAISS to **Weaviate** ,
a vector database that natively supports many of the system’s requirements:

**Advantages**
- Built-in vector indexing and hybrid search capabilities.
- Better horizontal scalability and operational characteristics than raw FAISS.
- Native support for metadata filtering and access control.

**Trade-off**
- Weaviate does not allow explicit selection of low-level distance algorithms
  (unlike FAISS in pure semantic search mode).

**Assessment**
This limitation becomes less relevant as:
- data volume grows,
- approximate nearest-neighbor methods dominate,
- and exact distance computation becomes impractical at scale.

Therefore, the lack of manual algorithm selection is not considered a blocking issue
for large-scale, production-oriented RAG systems.

## Consequences

### Pros
- Clear, contract-driven retrieval architecture.
- Strong separation between selection, graph expansion, and text loading.
- Improved security guarantees.
- Retrieval backend can evolve independently of pipeline logic.

### Cons
- Slightly increased pipeline length and conceptual complexity.
- Requires explicit contracts and validation for each retrieval stage.

## Summary

This ADR formalizes a **multi-stage retrieval model** aligned with Design by Contract principles.
It ensures deterministic, secure, and scalable retrieval while remaining flexible enough
to accommodate future backend and model changes.
