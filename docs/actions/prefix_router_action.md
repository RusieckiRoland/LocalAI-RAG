# PrefixRouterAction — contract and usage (routes-based)

Updated: 2026-01-13

## Purpose

`PrefixRouterAction` selects the next pipeline step based on a **prefix at the beginning** of the text stored in:

- `state.last_model_response`

## Input

The action reads:

- `state.last_model_response` (string)

## Step configuration (YAML)

A `prefix_router` step must define:

- `routes`: a non-empty mapping of `<kind>` → `{ prefix, next }`
- `on_other`: step id used when no prefix matches

### What “route” means

A **route** is one entry inside `routes`, addressed by its `<kind>` key.

For example, this YAML defines a route named `semantic`:

```yaml
routes:
  semantic:
    prefix: "[SEMANTIC:]"
    next: fetch_semantic
```

Including its fully-qualified fields:

- `routes.semantic.prefix` = `"[SEMANTIC:]"`
- `routes.semantic.next` = `"fetch_semantic"`

Meaning:

- if the text starts with `routes.semantic.prefix`, the router selects the `semantic` route and **sets the next step id** to `routes.semantic.next`
- the pipeline engine then executes the step with id `fetch_semantic`

### Required fields per route

For each `routes.<kind>`:

- `prefix`: non-empty string; the expected marker at the start of the text
- `next`: non-empty string; the step id to execute when the prefix matches

### Example: router decision step (from pipeline)

```yaml
- id: handle_router_prefix
  action: prefix_router
  routes:
    semantic:
      prefix: "[SEMANTIC:]"
      next: fetch_semantic
    bm25:
      prefix: "[BM25:]"
      next: fetch_bm25
    direct:
      prefix: "[DIRECT:]"
      next: call_model_answer
  on_other: call_model_answer
```

### Example: model output contract step (from pipeline)

```yaml
- id: handle_answer_prefix
  action: prefix_router
  routes:
    answer:
      prefix: "[Answer:]"
      next: finalize
    followup:
      prefix: "[Requesting data on:]"
      next: loop_guard
  on_other: finalize
```

## Runtime behavior

### 1) Validation (fail-fast)

Before routing, the action validates the step configuration:

- `routes` exists, is a mapping, and is not empty
- for every `kind` in `routes`:
  - `prefix` exists and is not empty after trimming
  - `next` exists and is not empty after trimming
- `on_other` exists and is not empty after trimming

If validation fails, the action raises an error and stops execution.

### 2) Prefix matching (whitespace trimming is always applied)

The action always removes leading and trailing whitespace from the input text:

- `text = (state.last_model_response or "").strip()`

Then it checks whether `text` starts with any configured `routes.<kind>.prefix`.

Routes are evaluated in the order they appear in `routes`.
If multiple prefixes match, the first matching route (by `routes` order) is selected.

### 3) On match

If a prefix matches:

- `state.last_prefix` is set to the matched `<kind>`
- the matched prefix is removed from the beginning of `text`
- the remaining text (payload) is trimmed and stored in `state.last_model_response`
- the action returns the next step id: `routes[<kind>].next`

The pipeline engine then executes the step with that id.

### 4) On no match

If no prefix matches:

- `state.last_prefix` is set to an empty string
- `state.last_model_response` is set to the input text with leading/trailing whitespace removed
  - no prefix is removed (because nothing matched)
- the action returns `on_other`

The pipeline engine then executes the `on_other` step.

## Outputs

The action writes:

- `state.last_prefix`
- `state.last_model_response`

The action returns the selected next step id (used by the pipeline engine).

## Checklist when authoring a prefix_router step

1) Ensure this prefix_router step is executed only after a step that writes routing text into state.last_model_response (for example a call_model step, but it may be any step that sets this field).
2) Ensure every `routes.<kind>.next` and `on_other` points to an existing step id in the pipeline.
3) Ensure route ordering in `routes` matches your intended precedence, because the first matching prefix wins.
4) Ensure model prompts and expected prefixes are consistent (the model must emit one of the configured prefixes).
