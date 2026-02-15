# `inbox_dispatcher` action

## Purpose
`inbox_dispatcher` enables **dynamic, model-suggested configuration** for downstream pipeline steps using the built-in per-run inbox/queue (`PipelineState.inbox`).

It reads `state.last_model_response` and enqueues allowlisted messages addressed to specific `step_id`s.

This is intentionally separated from `retrieval_filters` and other security-critical fields (snapshot/ACL/classification).

## Important note
The **concept** is broader than JSON: it is a generic dispatcher to the inbox.
The current implementation uses a best-effort **JSON-ish** parse of `last_model_response`, because model outputs are already structured as JSON in this pipeline. The action name does not assume JSON long-term.

## When to use
- You want the model to suggest optional runtime knobs (e.g. fetch/graph prioritization policy) without hard-wiring them into pipeline YAML.
- You want a generic mechanism to pass such knobs to multiple actions while still enforcing an allowlist.

## Contract (YAML step.raw)
```yaml
- id: dispatch_router_directives
  action: inbox_dispatcher
  directives_key: "dispatch"   # optional (default: "dispatch")
  rules:
    fetch_node_texts:          # target_step_id
      topic: "config"          # optional (default: "config")
      allow_keys: ["prioritization_mode", "policy"]
      rename:                 # optional
        policy: "prioritization_mode"
  next: handle_router_decision
```

Notes:
- Only `target_step_id`s present in `rules` are allowed.
- Only keys present in `allow_keys` are forwarded.
- `rename` can map model-friendly keys (e.g. `policy`) to action-friendly keys.

## Contract (model payload format)
The model can include a `dispatch` list in the same one-line response object it already returns:
```json
{
  "decision": "retrieve",
  "query": "class Category",
  "filters": {"data_type": "regular_code"},
  "search_type": "bm25",
  "dispatch": [
    {
      "target_step_id": "fetch_node_texts",
      "topic": "config",
      "payload": {"prioritization_mode": "balanced"}
    }
  ]
}
```

Accepted aliases for target:
- `target_step_id` (preferred)
- `target`
- `id`

Payload placement:
- Preferred: `payload: { ... }`
- Shorthand: keys may also be placed directly on the directive object (besides routing keys).

## Output
This action does not alter routing. It only enqueues inbox messages for later consumption.

