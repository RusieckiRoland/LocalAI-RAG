# `parallel_roads_action`

## Purpose
Initializes per-run memory for a parallel snapshot comparison flow.
This action is intentionally a no-op beyond state initialization.

It must be used together with `fork_action` and `merge_action`.

## Input
Reads:
- `state.parallel_roads` (optional; created if missing)

Writes:
- `state.parallel_roads` (initialized to `{}` if absent)

## Step configuration (YAML)
```yaml
- id: parallel_roads
  action: parallel_roads_action
  next: fork_snapshots
```

## Runtime behavior
- Ensures `state.parallel_roads` exists.
- Does not change routing (returns `None`).
