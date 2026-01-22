# `fetch_node_texts` 

## Purpose

`fetch_node_texts` takes a list of node IDs produced earlier in the pipeline and materializes their text content into `state.node_texts`, respecting a strict evidence budget and a deterministic ordering strategy.

---

## When to use this step

Use `fetch_node_texts` when your pipeline needs **evidence snippets** (code/text blocks) to be injected into the prompt as context for the model.

Most common placement:

`search_nodes → expand_dependency_tree (optional) → fetch_node_texts → render_context_blocks → call_model`

---

## What this step reads (pipeline state)

This action expects earlier steps to provide node IDs:

- `state.retrieval_seed_nodes`  
  Produced by: **`search_nodes`**  
  Meaning: “top ranked” node IDs from retrieval (semantic/BM25/hybrid)

- `state.graph_expanded_nodes` *(optional)*  
  Produced by: **`expand_dependency_tree`**  
  Meaning: additional node IDs discovered via dependency expansion

- `state.graph_edges` *(optional)*  
  Produced by: **`expand_dependency_tree`**  
  Used only for: computing `depth` / `parent_id` metadata and deterministic ordering

If **both** `retrieval_seed_nodes` and `graph_expanded_nodes` are empty → the action produces **no output**.

---

## YAML step configuration

### Supported fields

- `prioritization_mode: "seed_first" | "graph_first" | "balanced"` *(default: `"balanced"`)*
- `max_chars: int` *(optional)*
- `budget_tokens: int` *(optional)*
- `budget_tokens_from_settings: str` *(optional)* — key name from pipeline `settings`

### Budget rules (important)

You must choose **exactly one** budget mode:

✅ **Option A — character budget**
- `max_chars: <int>`

✅ **Option B — token budget**
- `budget_tokens: <int>`
  **or**
- `budget_tokens_from_settings: "<settings_key>"`

✅ **Option C — implicit token budget**
If you do not provide any explicit budget (`max_chars` / `budget_tokens` / `budget_tokens_from_settings`), then:
- the action uses **70% of** `settings.max_context_tokens`

❌ Forbidden combination  
- `max_chars` **cannot** be used together with **any** token budget option.

---

## How ordering works (prioritization strategies)

This action builds an **ordered candidate list of node IDs**, then walks it and applies budget limits.

### 1) `seed_first`

Order:
1. all seed nodes (in retrieval rank order)
2. then graph-only nodes ordered by: **depth asc, id asc**

Use when you want:
- maximum retrieval relevance first,
- graph expansion only as “extra context” if budget remains.

---

### 2) `graph_first`

Order:
For each seed in retrieval order:
1. seed
2. its descendants (same branch), ordered by: **depth asc, id asc**

Use when you want:
- each seed treated as a separate cluster/topic,
- local dependency context shown immediately after its seed.

This strategy is most useful when `expand_dependency_tree` is enabled and produces meaningful edges.

---

### 3) `balanced`

Order:
- interleave seed and graph nodes approximately 50/50
- always start with a seed
- graph nodes are pre-sorted by: **depth asc, id asc**

Use when you want:
- broad coverage (seeds + structural context),
- a “mixed evidence pack” under limited budget.

---

## Budget enforcement (“atomic skip” behavior)

Snippets are treated as **atomic**:

- if adding the next snippet would exceed the budget → that snippet is **skipped**
- the action continues checking later candidates
- **no early break** (so later smaller snippets may still fit)

This applies both to:
- token budgeting
- char budgeting

---

## What this step outputs

### `state.node_texts`

A list of dictionaries in the final selected order:

```json
[
  {
    "node_id": "A",
    "text": "…",
    "is_seed": true,
    "depth": 0,
    "parent_id": null
  }
]
```

Meaning of fields:
- `node_id`: the ID used through the pipeline
- `text`: materialized snippet (code/text)
- `is_seed`: whether it came from retrieval seeds
- `depth`: 0 for seeds, ≥1 for expanded nodes (if edges exist)
- `parent_id`: parent node ID in the BFS tree (if edges exist)

### `state.graph_debug`

Useful run metadata:
- `reason`: `"ok"` or `"no_nodes_for_fetch_node_texts"`
- `prioritization_mode`
- `seed_count`
- `graph_expanded_count`
- `node_texts_count`
- `budget_tokens`, `used_tokens`
- `max_chars`, `used_chars`

---

## YAML examples

### Example 1 — `max_chars`

```yaml
- id: fetch_texts
  action: fetch_node_texts
  prioritization_mode: seed_first
  max_chars: 12000
  next: render_context
```

### Example 2 — explicit token budget

```yaml
- id: fetch_texts
  action: fetch_node_texts
  prioritization_mode: balanced
  budget_tokens: 900
  next: render_context
```

### Example 3 — token budget read from pipeline settings

```yaml
settings:
  evidence_budget_tokens: 900

steps:
  - id: fetch_texts
    action: fetch_node_texts
    prioritization_mode: graph_first
    budget_tokens_from_settings: "evidence_budget_tokens"
    next: render_context
```

### Example 4 — implicit token budget from `max_context_tokens`

```yaml
settings:
  max_context_tokens: 4096

steps:
  - id: fetch_texts
    action: fetch_node_texts
    # no budget configured -> uses 70% of max_context_tokens
    prioritization_mode: balanced
    next: render_context
```

---

## Common failure modes (YAML-level)

1) **No node IDs available**
- Symptoms:
  - `state.graph_debug.reason = "no_nodes_for_fetch_node_texts"`
  - `state.node_texts = []`
- Cause:
  - `fetch_node_texts` executed before `search_nodes` (and before any expansion)
- Fix:
  - ensure `search_nodes` runs earlier, or provide seeds

2) **Conflicting budget configuration**
- Symptom:
  - error about `max_chars` not allowed with token budget
- Fix:
  - choose *either* `max_chars` *or* token budget

3) **Missing `max_context_tokens` when relying on implicit budget**
- Symptom:
  - error about `settings.max_context_tokens` missing
- Fix:
  - add `max_context_tokens` in `settings`
  - or set `budget_tokens` explicitly

4) **Wrong strategy name**
- Symptom:
  - invalid `prioritization_mode`
- Fix:
  - use only: `seed_first`, `graph_first`, `balanced`

5) **Unexpected ordering vs expectation**
- Typical cause:
  - using `balanced` when you expected strict “seed then its dependencies”
- Fix:
  - switch to `graph_first` if you want “seed + neighborhood”
  - use `seed_first` if you want “pure retrieval first”

---

## Minimal checklist (for YAML author)

- [ ] `fetch_node_texts` is placed **after** `search_nodes` (and optionally after `expand_dependency_tree`)
- [ ] Budget mode is **exactly one**:
  - [ ] `max_chars` **or**
  - [ ] `budget_tokens` / `budget_tokens_from_settings` **or**
  - [ ] `settings.max_context_tokens` is present (implicit mode)
- [ ] `prioritization_mode` is one of: `seed_first | graph_first | balanced`
- [ ] After a run, verify:
  - [ ] `state.graph_debug.reason == "ok"`
  - [ ] `state.node_texts` is non-empty when seeds/expanded nodes exist
