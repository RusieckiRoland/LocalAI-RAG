# JsonDecisionRouterAction — contract and usage (JSON decision-based)

Updated: 2026-02-14

## Purpose

`JsonDecisionRouterAction` selects the next pipeline step based on a **JSON decision object** stored in:

- `state.last_model_response`

This is useful when you want the model to emit routing decisions and retrieval parameters as JSON (instead of prefix-based routing).

## Input

The action reads:

- `state.last_model_response` (string)

Expected model output shape (one line JSON):

```json
{"decision":"direct"}
```

or:

```json
{"decision":"retrieve","query":"<search query>","filters":{"data_type":"regular_code"},"search_type":"bm25"}
```

## Step configuration (YAML)

A `json_decision_router` step must define:

- `routes`: a non-empty mapping of `<decision>` → `<next_step_id>`
- `on_other`: step id used when the decision is missing/unknown or when parsing fails

Example:

```yaml
- id: handle_router_decision
  action: json_decision_router
  routes:
    direct: call_model_direct_answer
    retrieve: search_auto
  on_other: call_model_direct_answer
```

## Decision key resolution

The action looks for a decision value in the JSON object using (in order):

1) `decision`
2) `route`
3) `mode`

The value is normalized by trimming and lowercasing before matching keys in `routes`.

## Runtime behavior

### 1) Validation (fail-fast)

Before routing, the action validates:

- `routes` exists, is a mapping, and is not empty
- `on_other` exists and is a non-empty string

If validation fails, the action raises an error and stops execution.

### 2) Parsing (best-effort)

The action attempts to parse `state.last_model_response` as a JSON-like object and is tolerant of common LLM mistakes:

- optional code fences
- unquoted keys (it will attempt to quote them)
- trailing commas
- `key=value` style assignments (it will attempt to convert to `key: value`)
- Python-dict style via `ast.literal_eval` as a fallback

If parsing fails (or the parsed value is not a dict), the action routes to `on_other` and leaves the payload unchanged.

### 3) Payload cleanup

If parsing succeeds, the action removes routing keys from the object:

- `decision`
- `route`
- `mode`

Then it writes the remaining object back into:

- `state.last_model_response`

as a compact JSON string (stable formatting, sorted keys). This is intended to leave downstream steps (e.g. `search_nodes` with a JSON-ish query parser) with a clean payload that contains only retrieval parameters.

### 4) Routing result

- If the resolved decision matches a key in `routes`, the action returns `routes[decision]`.
- Otherwise it returns `on_other`.

## Outputs

The action writes:

- `state.last_model_response` (cleaned JSON payload when parsing succeeds)

The action returns:

- the selected next step id (used by the pipeline engine)

## Checklist when authoring a json_decision_router step

1) Ensure a prior step writes a one-line JSON object into `state.last_model_response` (typically a `call_model` step).
2) Keep `routes` keys aligned with the prompt’s allowed `decision` values.
3) Set `on_other` to a safe fallback (e.g. direct answer or “not sure” answer).
4) Ensure downstream steps expect a JSON payload (because this action rewrites `state.last_model_response` to JSON on successful parse).
