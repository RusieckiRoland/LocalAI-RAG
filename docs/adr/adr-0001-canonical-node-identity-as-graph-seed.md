# ADR-0001: Canonical node identity (chunk_id/node_key) as the seed for graph-augmented retrieval

- **Status:** Accepted  
- **Date:** 2025-12-21  
- **Decision maker:** Roland (architecture owner for LocalAI-RAG / Indexer)  
- **Context:** LocalAI-RAG + indexer (RoslynIndexer) + planned domains: `frontEnd`, `dynamic_configuration`

## Context and problem statement

In the RAG pipeline we want to enrich retrieval results (Semantic / Semantic_Rerank / BM25 / Hybrid) with additional information connected through a dependency graph. The pipeline plan includes:

- `expand_dependency_tree` → graph expansion based on retrieval “seeds”
- `fetch_node_texts` → fetching texts for nodes added via graph expansion

Key requirements for graph expansion:
- deterministic (repeatable),
- independent of a specific retriever and its implementation identifiers,
- scalable to new domains (e.g., `frontEnd` with links to `regular_code`, and `dynamic_configuration` where UI/form behavior is driven by configuration).

The core decision is the **identity of the seeds**:
- Do we seed the graph with canonical indexer identifiers (`chunk_id` / `node_key`), or
- do we seed with retriever-oriented identifiers (`row_id`, `cs_key`, `db_key`) and then map them back to the graph?

## Decision

**We adopt Decision A: graph expansion is seeded with canonical indexer identifiers:**
- `chunk_id` (for C# / `regular_code` artifacts),
- `node_key` (for SQL/EF/InlineSQL / `db_code` artifacts).

Retrievers (Semantic, Rerank, BM25, Hybrid) must produce results that can be mapped directly to these canonical identifiers through `unified_metadata` (or an equivalent mechanism), without introducing additional “truth adapter” layers.

As a result, `expand_dependency_tree` operates on canonical IDs, and `fetch_node_texts` reads content from indexer artifacts (e.g., `chunks.json`, `sql_bodies.jsonl`) keyed by the same canonical IDs.

## Rationale

### Why this is architecturally preferable

1. **Single source of truth (Indexer → Graph → ID):**  
   The graph and its nodes are produced by the indexer; canonical identifiers are the natural join key.

2. **Stability over time:**  
   `row_id` and other retriever-specific identifiers are implementation details and can change with index rebuilds, chunking changes, metadata refactors, or tooling migrations.

3. **Easier extension to new domains:**  
   For `frontEnd` and `dynamic_configuration` we can add new node kinds and edge types while keeping the same mechanism: *retrieval → canonical seed → expansion → content fetch*.  
   This avoids creating separate mapping chains such as “front_key ↔ cs_key ↔ chunk_id”.

4. **Lower technical debt:**  
   We avoid accumulating mapping layers and heuristics that become a frequent source of subtle inconsistencies.

## Considered alternatives

### Option B: seeds based on retriever identifiers (`cs_key`, `db_key`, `row_id`)

**Description:**  
The graph would be seeded with retriever-dependent identifiers, which are then mapped to canonical graph IDs.

**Why rejected:**  
- Requires maintaining N:1 or 1:N mappings (e.g., a method split into multiple chunks).
- Increases coupling between the pipeline and a particular index/retriever implementation.
- Increases edge-case risk and “invisible” bugs, especially when adding new domains (frontEnd, dynamic_configuration).

## Consequences

### Pros

- Deterministic graph expansion independent of the retriever.
- A consistent data contract between the indexer, the graph, and the pipeline.
- Easier testing (results remain comparable across index rebuilds).
- Scales to new domains and new relation types.
- Better context-budget control (we can explain exactly which nodes were added and why).

### Cons / costs

- `unified_metadata` (or an equivalent layer) must expose `chunk_id` / `node_key` as first-class fields.
- Clear deduplication and ordering rules are required (e.g., priority: retrieval hits → graph-expanded).
- If chunking changes in the future, we must ensure `chunk_id` remains stable within a given build (which is already required for artifact consistency).

## Implementation implications (no code)

1. **Retrieval result contract:**  
   Each retriever must produce a result that maps to `chunk_id`/`node_key`.  
   Example: `row_id -> unified_metadata[row_id] -> {chunk_id|node_key}`.

2. **expand_dependency_tree:**  
   - Input: seed list (canonical IDs) + limits (`graph_max_depth`, `graph_max_nodes`, edge allowlist).
   - Output: `expanded_chunk_ids`, `expanded_node_keys` + diagnostics (which edges, what depth).

3. **fetch_node_texts:**  
   - Fetches texts for `expanded_*` without additional vector searches.
   - Text sources: indexer artifacts (e.g., `chunks.json`, `sql_bodies.jsonl`).

4. **Future domains (`frontEnd`, `dynamic_configuration`):**  
   - Add new node kinds and edge types to the graph.
   - Keep the same seeding and content-fetch mechanism.

## Notes

This decision enforces an approach based on unambiguous canonical node identifiers and deterministic joining: *retrieval → graph expansion → content fetch*. It keeps the architecture coherent and extensible while avoiding mapping layers that depend on retriever implementations.

