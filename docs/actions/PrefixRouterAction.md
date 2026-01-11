# PrefixRouterAction — purpose and usage

## What it is for

`PrefixRouterAction` is a pipeline action that acts as a **prefix-based router**:

- it selects the next pipeline path based on a **prefix** at the beginning of a text,
- it strips the matched prefix,
- it writes the remaining payload back into `state.last_model_response`.

Key rule: this action **does not** set retrieval filters and **does not** parse search queries. It is routing + stripping only.

## Where the input text comes from

The router reads from a **single source of truth**:

- `state.last_model_response`

It must not route based on `runtime.last_model_output` — the pipeline should be deterministic and state should be the only carrier of data between steps.

## What it does (step by step)

1) **Validates a strict step contract (no magic fallbacks)**:
   - if you define `<kind>_prefix`, you must define the matching `on_<kind>`
   - if you define `on_<kind>`, you must have `<kind>_prefix` (except `on_other`)
   - `on_other` is required (no match must not rely on implicit `next`)

2) **Matches a prefix** against the beginning of `state.last_model_response`.

3) On match:
   - sets `state.last_prefix` to the matched `kind`,
   - strips the prefix,
   - writes the payload into `state.last_model_response`,
   - returns the `next_step_id` from `on_<kind>`.

4) On no match:
   - keeps the text unchanged,
   - sets `state.last_prefix` to an empty value (implementation-specific),
   - returns `on_other`.

## What it writes to state

Typically:

- `state.last_prefix` — matched kind (`semantic`, `bm25`, `hybrid`, `direct`, `answer`, `followup`, …) or empty when unmatched,
- `state.last_model_response` — payload after stripping, or the full text when unmatched.

It **does not** touch retrieval fields, e.g.:

- `state.retrieval_filters`
- `state.retrieval_query`
- `state.retrieval_seed_nodes`
- `state.retrieval_mode` / `state.retrieval_scope`

## Step contract (StepDef.raw)

In YAML you define:

- `<kind>_prefix`: e.g. `bm25_prefix`, `semantic_prefix`, `direct_prefix`, …
- `on_<kind>`: e.g. `on_bm25`, `on_semantic`, `on_direct`, …
- `on_other`: fallback route when no prefix matches.

Common kinds used in pipelines:
- `bm25`, `semantic`, `hybrid`, `semantic_rerank`, `direct`
- `answer`, `followup` (when using model output contract prefixes)

## How to use it in a YAML pipeline

Router example (routing on a model decision):

```yaml
- id: prefix_router
  action: prefix_router
  bm25_prefix: "[BM25:]"
  semantic_prefix: "[SEMANTIC:]"
  hybrid_prefix: "[HYBRID:]"
  semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
  direct_prefix: "[DIRECT:]"
  on_bm25: fetch
  on_semantic: fetch
  on_hybrid: fetch
  on_semantic_rerank: fetch
  on_direct: call_answer
  on_other: call_answer
```

Contract-answer stripping example:

```yaml
- id: handle_answer
  action: prefix_router
  answer_prefix: "[Answer:]"
  followup_prefix: "[Requesting data on:]"
  on_answer: finalize
  on_followup: loop_guard
  on_other: finalize
```

## Common failure modes

- `semantic_prefix` present but `on_semantic` missing → contract error.
- `on_bm25` present but `bm25_prefix` missing → contract error.
- Missing `on_other` → contract error (no safe “no match” route).
- Running the router when `state.last_model_response` is empty (it will always go to `on_other`).

## Minimal checklist

1) Ensure `state.last_model_response` contains the routing text before `prefix_router` (usually output from `call_model`).
2) Define consistent `<kind>_prefix` + `on_<kind>` pairs.
3) Always set `on_other`.
4) Treat this action strictly as routing + stripping (retrieval is handled elsewhere).
