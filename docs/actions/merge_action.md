# `merge_action`

## Purpose
Collects retrieval results per snapshot, clears retrieval state, and builds a comparison context.
After the last snapshot, it appends the combined blocks to `state.context_blocks`.

This action must be paired with `fork_action`.

## Input
Reads:
- `state.node_texts` (retrieval results from `fetch_node_texts`)
- `state.parallel_roads` (snapshot plan and current index)
- `state.snapshot_friendly_names` (optional map: snapshot_id -> label)
- `step.raw.snapshots` (mapping of snapshot name -> label template)

Writes:
- `state.context_blocks` (appends per-snapshot blocks after final merge)
- `state.parallel_roads.results` (per-snapshot block lists)
- Clears retrieval artifacts: `node_texts`, `retrieval_seed_nodes`, `retrieval_hits`,
  `graph_seed_nodes`, `graph_expanded_nodes`, `graph_edges`, `graph_debug`
- Restores original `state.snapshot_id` and `state.snapshot_id_b` when finished

## Step configuration (YAML)
```yaml
- id: merge_snapshots
  action: merge_action
  snapshots:
    snapshot_a: "Branch {}"
    snapshot_b: "Branch {}"
  next: compare_and_answer
```

## Runtime behavior
- Uses `snapshots` mapping to render a label per snapshot.
- If `state.snapshot_friendly_names` contains a label for the snapshot id,
  it is used instead of the raw snapshot key.
- Stores each snapshot's node texts as blocks:
  - label line
  - repeated `--- NODE ---` blocks with id, path, text
- Clears retrieval state between iterations.
- Jumps back to `fork_action` until all snapshots are merged.
