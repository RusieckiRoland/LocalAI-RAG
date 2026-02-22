# Retrieval contract coverage checklist

This document compares requirements from `docs/contracts/retrieval_contract.md` with the integration tests described in `docs/tests/retrieval_integration_tests.md`.
It summarizes coverage gaps and missing tests.

## Legend
- ✅ covered (documented and/or tested)
- ⚠️ partially covered (described but not fully asserted)
- ❌ not covered (missing docs and tests)

## 1) `search_nodes` — contract vs coverage

- ✅ Supported modes: `semantic`, `bm25`, `hybrid`  
  Evidence: sections 1–3 in `retrieval_integration_tests.md`.

- ✅ Returns seed IDs (non‑empty) for deterministic cases  
  Evidence: “search_nodes returns at least one seed node”.

- ⚠️ Does not materialize text or `context_blocks`  
  No explicit assertion that `node_texts` / `context_blocks` remain empty.

- ❌ Fail‑fast for missing `repository` / `snapshot_id`  
  No negative contract tests.

- ❌ Enforced `top_k` (step or settings required)  
  No test for error on missing `top_k`.

- ❌ Rerank allowed only for `semantic`  
  No integration tests for rerank constraints.

- ⚠️ `retrieval_filters` are sacred and must not be overridden by parser  
  Tests mention filters but do not assert merge precedence.

## 2) `expand_dependency_tree` — contract vs coverage

- ✅ Expands graph with allowlist and limits  
  Evidence: section 6 in `retrieval_integration_tests.md`.

- ✅ Edge allowlist prevents disallowed relations  
  Evidence: dependency tree tests.

- ⚠️ `graph_max_depth` / `graph_max_nodes` respected  
  Described, but no explicit limit‑boundary tests.

- ❌ Fail‑fast for missing `repository`, `snapshot_id`, or missing `*_from_settings`  
  No negative contract tests.

- ⚠️ `graph_debug` completeness  
  Logged but not validated for required keys.

- ❌ Security trimming in graph expansion (ACL + classification)  
  No integration coverage.

## 3) `fetch_node_texts` — contract vs coverage

- ✅ Prioritization modes (`seed_first`, `graph_first`, `balanced`)  
  Evidence: tests F2–F4.

- ✅ Limits (`budget_tokens`, `max_chars`, `*_from_settings`)  
  Evidence: tests F5–F7.

- ✅ Atomic skip (no partial text fragments)  
  Evidence: test F8.
