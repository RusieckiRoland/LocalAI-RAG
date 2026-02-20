# `fork_action`

## Purpose
Runs the same retrieval step multiple times for different snapshots.
It sets `state.snapshot_id` to each snapshot in order and jumps into the configured `search_action`.

This action must be paired with `merge_action`.

## Input
Reads:
- `step.raw.snapshots` (mapping of name -> snapshot id or placeholder)
- `step.raw.search_action` (must point to a `search_nodes` step id)
- `state.snapshot_id` and `state.snapshot_id_b` (used by placeholders)

Writes:
- `state.snapshot_id` (current snapshot id for this fork iteration)
- `state.parallel_roads` (stores plan, index, original snapshot ids, results)

## Step configuration (YAML)
```yaml
- id: fork_snapshots
  action: fork_action
  search_action: search_nodes
  snapshots:
    snapshot_a: "${snapshot_id}"
    snapshot_b: "${snapshot_id_b}"
  next: search_nodes
```

## Runtime behavior
- Builds the snapshot plan from `snapshots`.
- Supports placeholders:
  - `${snapshot_id}` / `$snapshot_id` / `snapshot_id`
  - `${snapshot_id_b}` / `$snapshot_id_b` / `snapshot_id_b`
- Sets `state.snapshot_id` to the current snapshot and returns `search_action`.
- When all snapshots are processed, returns `step.raw.on_done` if provided, otherwise `None`.
