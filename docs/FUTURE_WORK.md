# File: docs/FUTURE_WORK.md

# Future work

This document tracks planned improvements for upcoming iterations.

## 1) Move BM25 to a Rust implementation (future replacement for the Python BM25)

### Goal
Migrate the lexical search engine (BM25) to Rust in order to:
- speed up build and/or query time (CPU hot path),
- use a stable, deterministic on-disk index format,
- reduce Python-side compute load and simplify long-term maintenance.

### Key invariant
BM25 must return results as **`row_id`**, where `row_id` is aligned with:
- the row index in `unified_metadata.json`,
- the row index in FAISS (`unified_index.faiss`),
- and (currently) the `doc_id` in the TF index.

This alignment guarantees a simple and reliable merge strategy (e.g., RRF) and consistent mapping back to metadata/chunks.

### Rust ↔ Python integration paths

#### Option A: Rust as an external process (CLI/daemon)
1) Rust builds a BM25 index in `vector_indexes/<index_id>/bm25_rust/`.
2) Python calls the Rust binary (e.g., via `subprocess`) with:
   - `index_dir`, `query`, `top_k`, optional filters (repo/branch/data_type/file_type).
3) Rust prints JSON to stdout: a list of `{ "row": <int>, "score": <float>, "rank": <int> }`.
4) Python merges FAISS + BM25 results using RRF.

Pros: easiest operationally; no Python wheel/build issues.  
Cons: IPC overhead; a small protocol to maintain.

#### Option B: Rust as a Python extension module (PyO3 / maturin)
1) Create a Rust crate that exposes functions such as:
   - `build_index(index_dir, texts, metadata_fields...)`
   - `search(index_dir, query, top_k, filters...) -> List[(row, score)]`
2) Package it as a Python module (wheels) and import it directly in the retriever code.
3) Python still owns FAISS + fusion (RRF); Rust owns BM25 scoring and indexing.

Pros: no external process; very fast calls.  
Cons: packaging/CI complexity; environment compatibility concerns.

### Migration plan (high level)
1) Define a stable contract:
   - input: `index_dir`, `query`, `top_k`, filters,
   - output: list of `(row_id, score)` or `(row_id, rank)` (RRF only needs ranks).
2) Enforce deterministic `row_id` alignment:
   - `row_id` is always the index into `unified_metadata.json`.
3) Build a prototype (Option A or B) on a small corpus and compare results with the current Python implementation.
4) After validation, switch the BM25 backend in `HybridSearch`:
   - keep FAISS retriever unchanged,
   - route BM25 retrieval to Rust,
   - keep RRF fusion logic unchanged.

### Architectural notes
- Treat Rust as a swappable “lexical engine” backend.
- The shared document identifier (`row_id`) is the non-negotiable contract between components.
- If metadata filters become important, either:
  - index selected fields in Rust (repo/branch/data_type/file_type), or
  - filter in Python using `row_id -> unified_metadata[row_id]`.
