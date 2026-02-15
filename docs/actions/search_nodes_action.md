# `search_nodes` action

This document explains how to use the **`search_nodes`** action in a YAML pipeline.

It is **fully consistent with `retrieval_contract.md`**:
- **fail-fast** (invalid config → runtime error)
- **deterministic** behavior (stable, ranked seed ordering)

---

## What `search_nodes` does

`search_nodes` is the **retrieval** step. It returns **canonical node/chunk IDs** (“seed nodes”) ordered by ranking.

This action:
- ✅ runs retrieval via the backend (`IRetrievalBackend`)
- ✅ writes IDs to `state.retrieval_seed_nodes`
- ✅ writes ranking diagnostics to `state.retrieval_hits`
- ❌ does **not** fetch text payloads
- ❌ does **not** build LLM context
- ❌ does **not** expand the dependency graph (that is `expand_dependency_tree`)

Typical pipeline flow:
1) `search_nodes` → seed IDs  
2) `expand_dependency_tree` → expanded IDs + edges  
3) `fetch_node_texts` → node texts for the LLM

---

## Search modes (`search_type`) — semantic / bm25 / hybrid

### `semantic`
**Embedding-based / vector** search:
- best for “descriptive” queries and conceptual intent
- works well with natural language over code

### `bm25`
**Lexical keyword** search:
- best when you have exact tokens: class/method names, column names, constants, error messages
- deterministic matching on terms

### `hybrid`
**Mixed** search:
- combines `semantic` + `bm25`
- typically uses rank fusion (e.g., RRF – Reciprocal Rank Fusion)
- practical goal: “semantic intent + don’t miss exact tokens”

> Note: the exact hybrid strategy and parameters depend on the retrieval backend.

---

## `rerank` (semantic-only)

### What is reranking?
A reranker is a post-processing step that improves the ordering of hits.
It does not change **what** was retrieved, only **how it is ranked** as seed nodes.

### Allowed values
```yaml
rerank: none | keyword_rerank | codebert_rerank
```

- `none` *(default)* — no reranking
- `keyword_rerank` — **supported today**: lightweight token/keyword-based rerank  
  - meaningful **only** for `semantic` to “tighten” ranking with hard tokens
- `codebert_rerank` — **future / planned** (contract placeholder)  
  - intended for CodeBERT/cross-encoder style reranking

### Contract rule (fail-fast)
- `rerank != none` is allowed **only** when `search_type: semantic`
- unknown `rerank` value → **runtime error**

---

## Query parser (`query_parser`) and filters

### Why a parser?
`query_parser` lets you split:
- the **query text**, and
- structured **filters** (e.g. `data_type`, tags, scoped constraints)

This is useful when a router/model emits a “JSON-ish” payload.

### Supported payload metadata (JSON-ish)
When using `JsonishQueryParser`, the model can include optional *top-level* metadata keys:
- `search_type` / `mode`: `semantic | bm25 | hybrid | semantic_rerank`
- `top_k`: integer (used only if `allow_top_k_from_payload: true`)
- `rrf_k`: integer (used only if `allow_rrf_k_from_payload: true` and resolved search is `hybrid`)
- `match_operator`: `and | or` (applied only when resolved search is `bm25`)

Notes:
- These metadata keys are **not** passed to the retrieval backend as filters.
- `bm25_operator` is used **only** when `match_operator` is explicitly present (`and|or`).
- If payload contains an invalid or missing `match_operator`, the action keeps `bm25_operator = null`.

### How it works in this action
1) `state.last_model_response` is parsed (if configured)
2) the parser returns:
   - `query`
   - `filters_parsed`
   - `warnings`
3) the action builds `filters_base` (repo/snapshot + ACL)
4) filters are merged contract-style:

**Security filters are sacred and must not be overridden by payload.**  
Therefore:

```
filters_effective = parsed_filters + base_filters
(base_filters override parsed_filters)
```

So even if the payload tries to spoof `repo/snapshot/tenant`, `base_filters` wins.

---

## Snapshot selector (`snapshot_source`)

`search_nodes` can choose which snapshot scope to use:

```yaml
snapshot_source: primary | secondary
```

- `primary` *(default)* → use `state.snapshot_id`
- `secondary` → use `state.snapshot_id_b`

Notes:
- `secondary` requires `snapshot_id_b` to be present.
- In API requests, frontend `snapshots[]` is mapped as:
  - first element -> `snapshot_id` (primary)
  - second element -> `snapshot_id_b` (secondary)

---

## Required state inputs (`PipelineState`)

Required:
- `state.last_model_response` *(required; becomes the query)*  
- `state.repository` *(required, non-empty)*  
- `state.retrieval_filters` *(optional but “sacred” security filters: `acl_tags_any`, `classification_labels_all`, etc.)*

Optional:
- `state.snapshot_id` *(required for default/primary mode)*
- `state.snapshot_id_b` *(required only for `snapshot_source: secondary`)*

---

## YAML configuration

### Minimal
```yaml
- id: retrieve
  action: search_nodes
  search_type: semantic
  top_k: 5
  next: expand_graph
```

### Full contract schema
```yaml
- id: <step_id>
  action: search_nodes

  search_type: semantic | bm25 | hybrid

  top_k: <int>                             # optional, default: 5
  query_parser: <string>                   # optional (e.g. jsonish_v1)
  rerank: none | keyword_rerank | codebert_rerank   # optional; semantic-only
  snapshot_source: primary | secondary               # optional; default: primary

  # optional (backend-dependent):
  rrf_k: <int>                             # typically hybrid-only (e.g. default 60)

  next: <next_step_id>
```

---

## Fail-fast validations

Runtime error if:
- `repository` is missing/empty
- `snapshot_source` is invalid
- `snapshot_source=secondary` and `snapshot_id_b` is missing
- `search_type` is not one of `semantic | bm25 | hybrid`
- `top_k < 1`
- query becomes empty after parsing/normalization
- `rerank` is unknown
- `rerank != none` while `search_type != semantic`

---

## Outputs written by this action

### Contract-required
- `state.retrieval_seed_nodes: List[str]`  
  Ranked node IDs used by the next actions.

### Helpful diagnostics
- `state.retrieval_hits: List[dict]`  
  Example shape:
  ```json
  [
    {"id":"<node_id>", "score":0.78, "rank":1},
    {"id":"<node_id>", "score":0.72, "rank":2}
  ]
  ```

- `state.last_search_bm25_operator: str | null`  
  Records effective operator when `search_type=bm25`
  (only explicit payload value).

---

## Cleanup at the start (important!)

`search_nodes` resets retrieval/graph/text artifacts to prevent cross-iteration leakage:

- `state.retrieval_seed_nodes = []`
- `state.retrieval_hits = []`
- `state.graph_seed_nodes = []`
- `state.graph_expanded_nodes = []`
- `state.graph_edges = []`
- `state.graph_debug = {}`
- `state.graph_node_texts = []`
- `state.context_blocks = []`

Additionally (defensive):
- if `state.node_texts` exists → set to `[]`

This matches the contract rule: **no accidental reuse of old results**.

---

## Common misconfigurations

1) `rerank: keyword_rerank` with `search_type: bm25`  
→ runtime error (contract: rerank is semantic-only)

2) missing `repository` or `branch`  
→ runtime error (contract: scope is required)

3) `top_k: 0`  
→ runtime error

---

## End-to-end example

```yaml
- id: retrieve
  action: search_nodes
  search_type: semantic
  top_k: 8
  query_parser: jsonish_v1
  rerank: keyword_rerank
  next: expand_graph

- id: expand_graph
  action: expand_dependency_tree
  max_depth_from_settings: graph_max_depth
  max_nodes_from_settings: graph_max_nodes
  edge_allowlist_from_settings: graph_edge_allowlist
  next: fetch_texts

- id: fetch_texts
  action: fetch_node_texts
  prioritization_mode: balanced
  next: render_context
```
