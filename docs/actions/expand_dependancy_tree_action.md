# `expand_dependency_tree` 

## Purpose

`expand_dependency_tree` takes **seed node IDs** (from `state.retrieval_seed_nodes`) and asks the graph provider to return **related nodes + edges**.
It stores the results in:

- `state.graph_expanded_nodes` (expanded node IDs)
- `state.graph_edges` (normalized edges)
- `state.graph_debug` (stable debug metadata)

This action is typically used between:

`search_nodes → expand_dependency_tree → fetch_node_texts`

---

## What it needs from the pipeline state

### Required
- `state.branch: str` — non-empty
- `state.repository: str` — non-empty *(can come from pipeline `settings.repository` if state doesn’t override it)*

### Optional (but common)
- `state.retrieval_seed_nodes: list[str]` — if empty, expansion is skipped
- `state.retrieval_filters: dict` — ACL/tenant filters passed through to the graph provider (if present)

---

## YAML step configuration

This action is **strict**: the step must declare three keys that point to pipeline settings.

### Required step fields
- `max_depth_from_settings: str`
- `max_nodes_from_settings: str`
- `edge_allowlist_from_settings: str` *(may point to a setting that is `null`)*

These must be **present in the YAML step**, even if the setting value is `null`.

### Example YAML step

```yaml
- id: expand
  action: expand_dependency_tree

  # REQUIRED: these must exist in the step
  max_depth_from_settings: "graph_max_depth"
  max_nodes_from_settings: "graph_max_nodes"
  edge_allowlist_from_settings: "graph_edge_allowlist"

  next: fetch_texts
```

### Required pipeline settings

The step references keys in `pipeline.settings`, so the settings must contain:

```yaml
settings:
  graph_max_depth: 2          # int >= 1
  graph_max_nodes: 200        # int >= 1
  graph_edge_allowlist: null  # null or list[str]
```

Rules:
- `graph_max_depth` must be `>= 1`
- `graph_max_nodes` must be `>= 1`
- `graph_edge_allowlist` must be either:
  - `null` *(meaning “no allowlist filter”)*, or
  - a list of strings

---

## Provider call

Internally the action calls the graph provider like this:

```python
result = graph_provider.expand_dependency_tree(
    seed_nodes=[...],
    repository=...,
    branch=...,
    max_depth=...,
    max_nodes=...,
    edge_allowlist=...,
    filters=...,  # from state.retrieval_filters
)
```

As a YAML author you **don’t configure** this call directly — you only control:
- which settings keys are used (`*_from_settings`)
- the values inside `pipeline.settings`

---

## Outputs written to `PipelineState`

### 1) `state.graph_seed_nodes`
Copy of the input seeds (for traceability):
```yaml
graph_seed_nodes = ["A", "B"]
```

### 2) `state.graph_expanded_nodes`
Expanded node IDs returned by provider:
```yaml
graph_expanded_nodes = ["A", "B", "C", "D"]
```

> Note: the provider may include the original seeds again — the action keeps whatever comes back in `result["nodes"]`.

### 3) `state.graph_edges`
Normalized edge objects:

**Required shape:**
```json
{
  "from_id": "A",
  "to_id": "B",
  "edge_type": "calls"
}
```

If the provider returns legacy-like keys (`from`, `to`, `type`), the action normalizes them deterministically.

If `edge_type` is missing, it becomes `"unknown"`.

### 4) `state.graph_debug`
Stable debug summary:

```json
{
  "reason": "ok",
  "seed_count": 2,
  "expanded_count": 10,
  "edges_count": 14
}
```

---

## Non-fatal behavior (when the action chooses to skip)

These cases do **not** fail the pipeline and simply produce empty graph results:

### Missing graph provider
If `runtime.graph_provider` is `None`:

- `graph_debug.reason = "missing_graph_provider"`
- `graph_expanded_nodes = []`
- `graph_edges = []`

### No seeds
If `state.retrieval_seed_nodes` is empty:

- `graph_debug.reason = "no_seeds"`
- `graph_expanded_nodes = []`
- `graph_edges = []`

### Provider does not implement `expand_dependency_tree`
If the provider object has no `expand_dependency_tree` method:

- `graph_debug.reason = "graph_provider_missing_expand_dependency_tree"`
- `graph_expanded_nodes = []`
- `graph_edges = []`

---

## Common failure modes (what you can fix in YAML)

1) **Missing required YAML fields**
- Symptom:  
  `Missing required 'max_depth_from_settings' in YAML step`
- Fix: add the missing `*_from_settings` field to the step.

2) **Empty `*_from_settings` value**
- Symptom:  
  `max_depth_from_settings must be a non-empty string`
- Fix: set it to a valid settings key name (e.g. `"graph_max_depth"`).

3) **Referenced settings key missing**
- Symptom:  
  `pipeline_settings missing 'graph_max_depth'`
- Fix: add the key to `pipeline.settings`.

4) **Bad setting type**
- Symptom:  
  `edge_allowlist must be a list or null`
- Fix: set `graph_edge_allowlist: null` or a list of strings.

5) **Invalid numeric values**
- Symptom:  
  `resolved max_depth must be >= 1`
- Fix: set `graph_max_depth` / `graph_max_nodes` to values `>= 1`.

---

## Minimal checklist (YAML-only)

- [ ] Step contains all three fields:
  - `max_depth_from_settings`
  - `max_nodes_from_settings`
  - `edge_allowlist_from_settings`
- [ ] Each field points to an existing key in `pipeline.settings`.
- [ ] `graph_max_depth >= 1` and `graph_max_nodes >= 1`.
- [ ] `graph_edge_allowlist` is either `null` or `["calls", "imports", ...]`.
- [ ] `pipeline.settings.repository` is set (or you ensure `state.repository` will be set earlier).
- [ ] `state.branch` will be set before this step runs.

---

## When to use `expand_dependency_tree`

Use it when you want the LLM to see **not only the most relevant chunks**, but also **their direct neighborhood**:
- call sites
- referenced symbols
- nearby files/types
- “what this code depends on”

Skip it (or keep allowlist narrow) when:
- your retrieval already returns enough evidence,
- you want the shortest possible context,
- graph expansion tends to explode node count for your repo.
