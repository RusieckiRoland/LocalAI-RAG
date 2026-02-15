# `manage_context_budget`

## Purpose

`manage_context_budget` is a pipeline action that enforces the **global prompt context budget** (`settings.max_context_tokens`)
by deciding whether to:

- append incoming retrieval texts (`state.node_texts`) into the prompt context (`state.context_blocks`), **or**
- refuse to append anything and route to `on_over` so the pipeline can compact the **existing context** first.

This action **does not replace** `fetch_node_texts`.
`fetch_node_texts` remains responsible for retrieval selection/materialization and its own evidence limits.
`manage_context_budget` is responsible for the **global** budget: *current context + incoming retrieval texts*.

---

## Typical placement in a pipeline

Most common layout:

`search_nodes → expand_dependency_tree (optional) → fetch_node_texts → manage_context_budget → call_model`

If `on_over` is used for context compaction, a common pattern is:

`... → fetch_node_texts → manage_context_budget → (on_over: call_summarize_context → set_context_from_summary) → manage_context_budget → ...`

Recommended safety:
- add a dedicated `loop_guard` for this retry loop to avoid infinite retries if compaction does not reduce enough.

---

## What this step reads (pipeline state)

Inputs:

- `state.context_blocks: List[str]` — current prompt context blocks.
- `state.node_texts: List[dict]` — incoming retrieval texts produced by `fetch_node_texts`.
- `runtime.pipeline_settings.max_context_tokens: int` — global context budget (required).
- `runtime.token_counter` — token counting implementation (required; no heuristics allowed).
- `state.inbox_last_consumed: List[dict]` — used only for `policy: demand` (see below).

Notes:

- Prompt building (system prompt + user parts + history) is owned by `call_model`. This action only manages the context material stored in `state.context_blocks`.
- `PipelineState.composed_context_for_prompt()` is treated as legacy and is **not** used by this action.

---

## What this step writes to state

On success (`on_ok`):

- appends formatted node texts to `state.context_blocks`
- clears `state.node_texts = []` (retrieval buffer consumed)

On over-budget (`on_over`):

- does **not** modify `state.context_blocks`
- does **not** modify `state.node_texts` (so the pipeline can retry after compacting existing context)

---

## YAML step configuration

### Required fields

- `on_ok: <step_id>`
- `on_over: <step_id>`

### Optional compaction rules

```yaml
compact_code:
  rules:
    - language: sql
      policy: demand
      inbox_key: compact_sql
    - language: sql
      policy: threshold
      threshold: 0.4
    - language: dotnet
      policy: always
```

Rules:

- `compact_code.rules` must be a list.
- **First matching rule wins** (per `language`).
- `language`: `sql | dotnet`
- `policy`: `always | threshold | demand`
- `threshold`: fraction of `max_context_tokens` in `(0, 1]`
  - meaning: fraction of the global budget used as the “compaction trigger”
  - example: `max_context_tokens=5000`, `threshold=0.4` → trigger at `2000` tokens
- `demand` requires `inbox_key`.

Validation is **fail-fast** (invalid policy, missing threshold, invalid range, missing inbox_key, etc.).

---

## Language detection (SQL vs .NET)

This action detects language per node text using the single source of truth:

- `classifiers/code_classifier.py`

Minimum behavior:

- SQL → `sql`
- DOTNET / DOTNET_WITH_SQL → `dotnet`
- otherwise → `unknown` (no compaction rule matches `unknown`)

---

## Compaction policies

Compaction is applied **per node**, before deciding to append it.

### `policy: always`

Always compact matching language nodes before evaluating the global budget.

### `policy: threshold`

Compact only if adding the raw candidate would exceed:

`threshold * settings.max_context_tokens`

### `policy: demand` (inbox-driven)

Compact only if the step received a demand request via inbox messaging:

- the action checks `state.inbox_last_consumed`
- it considers the demand present if any consumed message satisfies:
  - `msg.target_step_id == <this step id>`
  - `msg.topic == inbox_key`

**Important retry semantics**

Inbox messages are consumed and cleared on step entry. To make `demand` persist across retries:

- if the action routes to `on_over`, it **re-enqueues** the demand message back to itself
  (`target_step_id=<this step id>`, `topic=inbox_key`)
- if the action routes to `on_ok`, it does not re-enqueue (demand is considered used)

---

## Budget semantics and pipeline misconfiguration

The intention is:

- `fetch_node_texts` enforces a retrieval evidence budget (e.g. 3000 tokens).
- if `manage_context_budget` still overflows the global budget, the cause should be the **existing context**, not the retrieval buffer.

Misconfiguration guard:

If the incoming retrieval buffer **alone** cannot fit into `settings.max_context_tokens`,
the action raises a fail-fast error:

- `PIPELINE_BUDGET_MISCONFIG: fetch_node_texts produced retrieval texts that cannot fit into settings.max_context_tokens ...`

This indicates the pipeline limits are inconsistent (e.g., retrieval budget > global budget).

---

## Formatting (`format_text`)

Every node is wrapped deterministically so the model can read it:

```text
--- NODE ---
id: <id>
path: <path>
language: sql
compact: true
text:
<...>
```

Fields:

- `id` (if present)
- `path` / `source` (best-effort from node metadata)
- `language`
- `compact: true/false`
- `text`

---

## Transitions (`on_ok` / `on_over`)

### `on_ok`

When all nodes can be appended without exceeding `max_context_tokens`:

1) append formatted texts to `state.context_blocks`
2) clear `state.node_texts`
3) return `on_ok`

### `on_over`

If adding a node would exceed `max_context_tokens` (even after optional compaction):

1) append nothing
2) keep `state.node_texts` unchanged
3) re-enqueue demand requests (if any were consumed)
4) return `on_over`

---

## Tracing / logging

This action emits a structured trace event:

- `event_type = "MANAGE_CONTEXT_BUDGET"`
- per node: language, policy, compacted flag, token counts before/after
- decision: `on_ok` / `on_over`

Additionally, base action tracing may include inbox consume/enqueue summaries.

---

## Example: minimal step (no compaction)

```yaml
- id: manage_budget
  action: manage_context_budget
  on_ok: call_model_answer
  on_over: call_summarize_context
```

### Optional: mark newly appended batches

You can inject a visible divider **only when a new retrieval batch is appended**
to `state.context_blocks`:

```yaml
divide_new_content: "<<<New content"
```

Behavior:
- the divider is inserted **once per appended batch** (right before the newly
  appended formatted nodes),
- it is **not** added when the action routes to `on_over`,
- it does **not** persist as a permanent prefix across turns (it becomes part of
  the previous context on the next turn).

---

## Example: demand + threshold + always

```yaml
- id: manage_budget
  action: manage_context_budget
  compact_code:
    rules:
      - language: sql
        policy: demand
        inbox_key: compact_sql
      - language: sql
        policy: threshold
        threshold: 0.4
      - language: dotnet
        policy: always
  on_ok: call_model_answer
  on_over: call_summarize_context
```

---

## Example: on_over compaction loop (call_model + set_variables + retry)

```yaml
- id: manage_budget
  action: manage_context_budget
  on_ok: call_model_answer
  on_over: budget_loop_guard

- id: budget_loop_guard
  action: loop_guard
  max_turn_loops_from_settings: "max_turn_loops"
  on_allow: call_summarize_context
  on_deny: call_model_answer

- id: call_summarize_context
  action: call_model
  prompt_key: "sumarizer"
  max_output_tokens: 2000
  user_parts:
    context:
      source: context_blocks
      template: "### Context:\n{}\n\n"
    user_question:
      source: user_question_en
      template: "### User:\n{}\n\n"
  next: set_context_from_summary

- id: set_context_from_summary
  action: set_variables
  rules:
    - set: context_blocks
      from: last_model_response
      transform: to_context_blocks
    - set: last_model_response
      value: null
  next: manage_budget
```

This loop compacts the **existing** `context_blocks`, then retries appending `node_texts` under the global budget.

---

## Common failure modes

- Missing `settings.max_context_tokens` → fail-fast error.
- Using `policy: threshold` without `threshold` → fail-fast error.
- `threshold` outside `(0, 1]` → fail-fast error.
- Using `policy: demand` without `inbox_key` → fail-fast error.
- Retrieval buffer alone exceeds global budget → `PIPELINE_BUDGET_MISCONFIG` error.

---

## Checklist for pipeline authors

- [ ] Ensure `settings.max_context_tokens` is present and realistic.
- [ ] Ensure retrieval budget in `fetch_node_texts` is compatible with global budget.
- [ ] Place this step **after** `fetch_node_texts` and **before** `call_model`.
- [ ] If you use `demand`, send messages addressed to this step id with `topic=inbox_key`.
- [ ] Ensure `on_ok` and `on_over` step ids exist.
