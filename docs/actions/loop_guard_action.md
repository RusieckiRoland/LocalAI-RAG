# `loop_guard`

## Purpose
`loop_guard` limits how many times the pipeline can loop through follow-up/retrieval cycles in a single run.

It increments a per-step counter in `state.loop_counters[step_id]` and routes to either `on_allow` or `on_deny`
based on `settings.max_turn_loops`.

## Input
Reads:
- `runtime.pipeline_settings.max_turn_loops` (default: 4)
- `state.loop_counters`
- step raw:
  - `on_allow`
  - `on_deny`

Writes:
- `state.loop_counters[<this step id>]`

## Step configuration (YAML)
```yaml
- id: loop_guard
  action: loop_guard
  max_turn_loops_from_settings: "max_turn_loops"   # note: used by pipeline authoring, action reads from settings
  on_allow: call_model_router
  on_deny: finalize
```

## Runtime behavior
- If current counter `< max_turn_loops` → increment and return `on_allow`.
- Otherwise → return `on_deny`.

