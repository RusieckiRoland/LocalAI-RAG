# RepeatQueryGuardAction — contract and usage (anti-repeat retrieval query)

Updated: 2026-02-15

## Purpose

`repeat_query_guard` prevents running the same retrieval query multiple times within one pipeline run.

It checks whether the current query (from `state.last_model_response`) was already asked earlier in this run and routes to:

- `on_ok` when query is new and non-empty
- `on_repeat` when query is empty or already seen (after normalization)

This step is typically placed after a decision router and before `search_nodes`.

## Input

The action reads:

- `state.last_model_response` (query payload, usually JSON-ish)
- `state.retrieval_queries_asked_norm` (set of normalized queries already executed)

Optional parser:

- `query_parser` in YAML; supported values:
  - `JsonishQueryParser`
  - `jsonish_v1`

If `query_parser` is omitted, the raw payload string is treated as the query.

## Step configuration (YAML)

Required fields:

- `on_ok`
- `on_repeat`

Optional fields:

- `query_parser`

Example:

```yaml
- id: guard_repeat_query
  action: repeat_query_guard
  query_parser: JsonishQueryParser
  on_ok: search_auto
  on_repeat: suff_loop_guard
```

## Runtime behavior

### 1) Validation (fail-fast)

At runtime, the action validates:

- `on_ok` is non-empty
- `on_repeat` is non-empty

Otherwise it raises an error.

### 2) Query extraction

- If `query_parser` is configured, the parser extracts `query` from payload.
- If parser is not configured, the whole payload is used as query text.
- If parser name is unknown, the action raises an error.

### 3) Normalization

Query is normalized by:

- trim
- lowercase
- collapsing repeated whitespace

So `" class   Foo "` and `"CLASS foo"` are treated as the same query.

### 4) Routing decision

- normalized query is empty -> return `on_repeat`
- normalized query already in `state.retrieval_queries_asked_norm` -> return `on_repeat`
- otherwise -> return `on_ok`

## What this action does not do

- It does **not** execute retrieval.
- It does **not** append query history itself.
- It does **not** rewrite `state.last_model_response`.

Query history is updated by `search_nodes` when retrieval actually executes.

## Why this is not `set_variables`

`set_variables` is for deterministic state mapping only (copy/transform/clear).  
`repeat_query_guard` adds decision logic and dynamic branching (`on_ok` vs `on_repeat`) based on run-time state and query history.

So these actions solve different problems:

- `set_variables`: mutate fields
- `repeat_query_guard`: protect control flow from duplicate retrieval attempts

## Typical placement in pipeline

```yaml
- id: handle_sufficiency_decision
  action: json_decision_router
  routes:
    sufficient: call_model_sure_answer
    retrieve: guard_repeat_query
  on_other: call_model_answer_not_sure

- id: guard_repeat_query
  action: repeat_query_guard
  query_parser: JsonishQueryParser
  on_ok: search_auto
  on_repeat: suff_loop_guard
```

This prevents loops like:

`sufficiency_router -> retrieve same query -> same evidence -> sufficiency_router -> ...`

## Quick examples

Example A (new query):

- payload query: `"class PaymentService definition"`
- already asked set: `{ "class orderservice definition" }`
- result: `on_ok`

Example B (repeat after normalization):

- payload query: `"  CLASS   PaymentService   definition "`
- already asked set contains: `"class paymentservice definition"`
- result: `on_repeat`

Example C (empty query):

- payload query: `""`
- result: `on_repeat`
