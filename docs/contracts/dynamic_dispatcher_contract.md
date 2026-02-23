# Dynamic Dispatcher Contract (Pipeline Inbox Messaging)

**Version:** 1.0  
**Date:** 2026-02-15  
**Status:** active contract

## 1. Contract goal

This document defines the **multi-component system contract** for dynamic pipeline input via `inbox_dispatcher`.

Scope:
- model output format (the `dispatch` section),
- directive validation and addressing by `inbox_dispatcher`,
- message format in `PipelineState.inbox`,
- message consumption semantics by actions,
- security and determinism invariants,
- test scenarios that can be automated.

> This is not a single-action document.
> Documents in `docs/actions/*` describe individual steps.
> This contract describes the **coordination protocol** between model, dispatcher, engine, state, and consumer actions.

---

## 2. Covered components

1) `call_model`  
- emits JSON (decision + optional `dispatch`).

2) `inbox_dispatcher`  
- reads directives from model output,
- filters and maps payload using `rules`,
- enqueues messages into `state.inbox`.

3) `json_decision_router` (typically in the same phase)  
- chooses flow branch (`next_step_id`) from `decision/route/mode`.

4) `PipelineState` (`inbox`, `enqueue_message`, `consume_inbox_for_step`)  
- stores per-run messages,
- enforces addressing by `target_step_id`.

5) `PipelineActionBase.execute`  
- at step entry, consumes messages addressed to `step.id`,
- writes consumed messages to `state.inbox_last_consumed`.

6) consumer actions (for example `fetch_node_texts`, `manage_context_budget`)  
- read `state.inbox_last_consumed`,
- apply domain logic.

---

## 3. Definitions

- **Directive**: an object in model output `dispatch`.
- **Target**: `target_step_id` (or alias `target` / `id`) referencing `StepDef.id`.
- **Topic**: message-type label (not an address).
- **Payload**: directive data after allowlist filtering.
- **Inbox message**: final object appended to `state.inbox`.

---

## 4. Data contract

## 4.1. Model output contract (dispatcher-relevant fragment)

The model may return:

```json
{
  "decision": "retrieve",
  "query": "class PaymentService definition",
  "dispatch": [
    {
      "target_step_id": "fetch_node_texts",
      "topic": "config",
      "payload": { "policy": "seed_first" }
    }
  ]
}
```

`dispatch` may be:
- a list of objects,
- a single object (treated as a one-element list).

Non-object entries are ignored.

## 4.2. `inbox_dispatcher` step configuration contract (YAML)

```yaml
- id: dispatch_router_directives
  action: inbox_dispatcher
  directives_key: "dispatch"   # optional; default: "dispatch"
  rules:
    fetch_node_texts:          # target_step_id
      topic: "config"          # optional; default: "config"
      allow_keys: ["prioritization_mode", "policy"]   # required for any payload key to pass
      rename:                  # optional
        policy: "prioritization_mode"
  next: handle_router_decision
```

`rules` is a per-target map:
- key = allowed `target_step_id`,
- value = payload filtering/mapping rule for that target.

## 4.3. Inbox message contract

A message in `state.inbox` has this shape:

```json
{
  "target_step_id": "<step_id>",
  "topic": "<non-empty string>",
  "payload": { "...": "..." }
}
```

Requirements:
- `target_step_id` required,
- `topic` required,
- `payload` optional, but if present it must be a `dict` and JSON-serializable.

---

## 5. Deterministic `inbox_dispatcher` algorithm

Input:
- `state.last_model_response` (string),
- `step.raw` (`directives_key`, `rules`).

Algorithm:

1) Read `directives_key`; default is `"dispatch"`.  
2) Normalize `rules`:
- if `rules` is not a dict, treat as an empty rule set.
3) Parse `last_model_response` as object (best-effort):
- strict JSON,
- repairs (`unquoted keys`, trailing commas),
- fallback to `ast.literal_eval`.
4) If payload is not an object -> **exit without enqueue**.  
5) Extract directives from `obj[directives_key]`:
- dict -> one directive,
- list -> only dict entries.
6) For each directive:
- resolve target in this order: `target_step_id` -> `target` -> `id`,
- if empty -> drop directive,
- if target not present in `rules` -> drop directive,
- resolve `topic`:
  1. `directive.topic`,
  2. `rules[target].topic`,
  3. `"config"`,
- build candidate payload:
  - preferred: `directive.payload` (if dict),
  - otherwise shorthand: all directive keys except routing keys (`target_step_id`, `target`, `id`, `topic`, `payload`),
- filter keys by `allow_keys` (missing or empty `allow_keys` means no key passes),
- apply `rename`,
- if filtered payload is empty -> drop directive,
- enqueue message:
  - `target_step_id=target`,
  - `topic=resolved_topic`,
  - `payload=filtered_payload`,
  - `sender_step_id=step.id`.
7) Action returns `None`; routing proceeds via `step.next` (or another action override).

Determinism:
- no randomness,
- directive order in output equals directive order in input `dispatch`.

---

## 6. Addressing and delivery contract

1) Addressing is based only on `target_step_id`.  
2) `topic` does not affect delivery; it is semantic label for consumer logic.  
3) At step entry, every action:
- takes only messages where `msg.target_step_id == step.id`,
- removes them from global inbox,
- stores them in `state.inbox_last_consumed`.
4) Message consumption is one-time (consume-once).
5) If target step is not executed by end of run, message remains in inbox.
- with `RAG_PIPELINE_INBOX_FAIL_FAST=1`, run ends with `PIPELINE_INBOX_NOT_EMPTY`.

---

## 7. Consumer-side contract (domain examples)

## 7.1. `fetch_node_texts`

Consumes dynamic override:
- `payload.prioritization_mode` (or legacy `payload.policy`).

Allowed values:
- `seed_first`
- `graph_first`
- `balanced`

If override value is outside allowed set -> runtime error.
If override is missing -> use YAML `prioritization_mode`, or default `balanced`.

## 7.2. `manage_context_budget` (`policy: demand`)

The step checks message topics in consumed inbox messages:
- if `msg.topic == inbox_key`, `demand` is considered active.

Example:
- `topic: compact_sql` activates SQL compaction on demand.

---

## 8. Security invariants

1) Dynamic data passes only through `rules[target].allow_keys`.  
2) `inbox_dispatcher` cannot rewire pipeline topology.  
3) `inbox_dispatcher` does not choose next step (router responsibility).  
4) Retrieval security scope fields (repo/snapshot/ACL/classification) must not be opened accidentally via permissive `allow_keys`.
- If such keys are intentionally allowed, this must be an explicit, tested decision.

---

## 9. Deterministic examples (payload -> messages)

Assumed `rules`:

```yaml
rules:
  fetch_node_texts:
    topic: "config"
    allow_keys: ["prioritization_mode", "policy"]
    rename:
      policy: "prioritization_mode"
  manage_budget:
    topic: "compact_sql"
    allow_keys: ["why", "retry"]
```

What the `manage_budget` rule contributes:
- allows the model to send an explicit **demand-type signal** to step `manage_budget` (action `manage_context_budget`),
- signal is recognized by `topic: "compact_sql"`,
- it is effective only when `manage_context_budget` includes `compact_code.rules[*]` with:
  - `policy: demand`
  - `inbox_key: compact_sql`.

Practical meaning of fields:
- `target_step_id: "manage_budget"`:
  - addresses the message to the exact step with `step.id = manage_budget`.
- `topic: "compact_sql"`:
  - does not address delivery; it tells the consumer "this is an SQL compaction request".
  - `manage_context_budget` checks `msg.topic == inbox_key`.
- `allow_keys: ["why", "retry"]`:
  - only these payload keys may pass,
  - every other key is dropped by dispatcher,
  - this matters because an empty filtered payload means no enqueue.

Role of `why` and `retry`:
- `why`:
  - diagnostic/audit field (for example `"tight_budget"`),
  - helps explain in trace why directive was sent.
- `retry`:
  - intent flag (for example retry signal),
  - compatible with current `manage_context_budget` behavior where on `on_over` it re-enqueues demand topic with payload `{"retry": true}`.

Note:
- in current implementation `manage_context_budget` activates `demand` based on `topic`, not payload content;
- payload still provides value for trace/debug and keeps contract extensible.

### Example A: two valid targets (full walkthrough)

Initial assumption:
- `state.inbox = []`

Input:

```json
{
  "dispatch": [
    {
      "target_step_id": "fetch_node_texts",
      "payload": {"policy":"seed_first","x":1}
    },
    {
      "target_step_id": "manage_budget",
      "topic":"compact_sql",
      "payload":{"why":"tight_budget"}
    }
  ]
}
```

Rule interpretation:
- for `fetch_node_texts`:
  - default topic is `"config"`,
  - allowed payload keys: `prioritization_mode`, `policy`,
  - mapping: `policy -> prioritization_mode`.
- for `manage_budget`:
  - default topic is `"compact_sql"`,
  - allowed payload keys: `why`, `retry`.

Processing `dispatch[0]`:
1) `target_step_id = "fetch_node_texts"` -> allowed target (present in `rules`).  
2) `topic` not provided -> fallback to `rules.fetch_node_texts.topic`, so `"config"`.  
3) Candidate payload: `{"policy":"seed_first","x":1}`.  
4) Allowlist filter:
- `policy` passes,
- `x` is dropped (not in `allow_keys`).  
5) Rename:
- `policy` becomes `prioritization_mode`.  
6) Dispatcher enqueues:

```json
{"target_step_id":"fetch_node_texts","topic":"config","payload":{"prioritization_mode":"seed_first"}}
```

Processing `dispatch[1]`:
1) `target_step_id = "manage_budget"` -> allowed target.  
2) `topic = "compact_sql"` provided explicitly -> used directly (no fallback).  
3) Candidate payload: `{"why":"tight_budget"}`.  
4) Allowlist filter:
- `why` passes.  
5) No `rename` for this target -> payload unchanged.  
6) Dispatcher enqueues:

```json
{"target_step_id":"manage_budget","topic":"compact_sql","payload":{"why":"tight_budget"}}
```

`state.inbox` after dispatcher completes (order preserved):

```json
[
  {"target_step_id":"fetch_node_texts","topic":"config","payload":{"prioritization_mode":"seed_first"}},
  {"target_step_id":"manage_budget","topic":"compact_sql","payload":{"why":"tight_budget"}}
]
```

How actions consume these messages:
- when step `fetch_node_texts` executes, it receives only the first message (addressed to `fetch_node_texts`),
- second message remains in inbox until step `manage_budget` executes,
- when `manage_budget` executes, it consumes the second message and inbox becomes empty (consume-once).

### Example B: target alias + payload shorthand

Input:

```json
{"dispatch":[{"id":"fetch_node_texts","policy":"balanced"}]}
```

Output:

```json
{"target_step_id":"fetch_node_texts","topic":"config","payload":{"prioritization_mode":"balanced"}}
```

### Example C: rejected directives

Input:

```json
{
  "dispatch": [
    {"target_step_id":"unknown_step","payload":{"a":1}},
    {"target_step_id":"fetch_node_texts","payload":{"a":1}},
    {"payload":{"policy":"seed_first"}}
  ]
}
```

Output:
- no enqueue (0 messages).

Reason:
- unknown target,
- no allowed payload keys,
- missing target.

---

## 10. Traceability contract

System should emit:
- `ENQUEUE` for every `state.enqueue_message(...)`,
- `CONSUME` at every step entry (including count=0),
- `RUN_END` with remaining inbox messages.

This is the source of truth for dispatcher protocol debugging.

---

## 11. Contract test matrix (minimum)

1) `dispatch` as list + valid target + valid keys -> 1+ inbox messages.  
2) `dispatch` as dict -> treated as one directive.  
3) missing `dispatch` -> 0 messages.  
4) target outside `rules` -> directive rejected.  
5) missing/empty `allow_keys` -> directive rejected.  
6) `rename` works deterministically (`policy -> prioritization_mode`).  
7) topic fallback chain works (`directive.topic` > `rules.topic` > `"config"`).  
8) message is delivered only to step where `step.id == target_step_id`.  
9) consume removes message from global inbox (consume-once).  
10) unconsumed target leaves message; with `RAG_PIPELINE_INBOX_FAIL_FAST=1` run fails.  
11) `manage_context_budget` activates `policy=demand` only when `topic == inbox_key`.  
12) `fetch_node_texts` applies inbox `prioritization_mode` override and validates allowed values.

---

## 12. Evolution recommendations

1) Introduce new dynamic keys only via explicit `allow_keys` per target.  
2) Keep responsibility boundaries strict:
- flow routing in routers,
- dynamic parameters in dispatcher/inbox.
3) Keep contract tests updated whenever prompt or `rules` change.  
4) Treat this document as normative for E2E and action-level tests.
