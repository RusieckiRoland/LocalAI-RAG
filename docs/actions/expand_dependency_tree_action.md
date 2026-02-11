# `expand_dependency_tree`

## Purpose
`expand_dependency_tree` takes **seed node IDs** from `state.retrieval_seed_nodes` and asks the configured
graph provider to expand the dependency neighborhood (nodes + edges). It stores normalized outputs on state.

Typical use:
`search_nodes → expand_dependency_tree → fetch_node_texts`

## Input
Reads:
- `state.retrieval_seed_nodes`
- `state.repository` (or `runtime.pipeline_settings.repository`)
- `state.branch` *(required; must be set before this step)*
- `state.retrieval_filters` *(passed through to provider)*
- `runtime.graph_provider`

## Step configuration (YAML)
This step is strict and requires three `*_from_settings` keys in the step:

```yaml
- id: expand
  action: expand_dependency_tree
  max_depth_from_settings: "graph_max_depth"
  max_nodes_from_settings: "graph_max_nodes"
  edge_allowlist_from_settings: "graph_edge_allowlist"
  next: fetch_texts
```

The referenced pipeline settings must exist and be valid:

```yaml
settings:
  graph_max_depth: 2
  graph_max_nodes: 120
  graph_edge_allowlist: null   # or list[str]
```

## Runtime behavior
- If `runtime.graph_provider` is missing → non-fatal no-op (empty graph outputs, debug reason set).
- If there are no seeds → non-fatal no-op (empty graph outputs, debug reason set).
- Otherwise → calls `graph_provider.expand_dependency_tree(...)` and normalizes:
  - nodes list
  - edges to `{from_id, to_id, edge_type}` (with `edge_type="unknown"` if missing)

Writes:
- `state.graph_seed_nodes`
- `state.graph_expanded_nodes`
- `state.graph_edges`
- `state.graph_debug`

