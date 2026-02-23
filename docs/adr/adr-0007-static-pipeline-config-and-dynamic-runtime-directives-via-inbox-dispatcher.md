# ADR-0007: Static pipeline config with controlled dynamic runtime directives via `inbox_dispatcher`

- **Status:** Accepted  
- **Date:** 2026-02-15  
- **Decision maker:** Roland (architecture owner for LocalAI-RAG)  
- **Related:** ADR-0002 (Design by Contract for YAML pipelines), ADR-0003 (Retrieval model), ADR-0005 (Retrieval backend abstraction)

## Context

LocalAI-RAG uses YAML-defined pipelines where:
- step topology and default behavior are defined statically,
- model output is used at runtime for routing and retrieval parameters.

With the introduction of `json_decision_router` and `inbox_dispatcher`, we need a clear architectural rule for:

- what remains static and authoritative in YAML,
- what may be dynamic and model-suggested at runtime.

The core tension:

1) **Static-only approach** is deterministic and safe, but rigid and expensive to evolve when small runtime tuning is needed.  
2) **Dynamic-only approach** is flexible, but risks non-determinism, hidden coupling, and unsafe overrides of critical fields.

## Decision

We adopt a **hybrid governance model**:

1) **Static YAML pipeline is the source of truth** for control topology and defaults:
   - existing steps and transitions (`next`, `on_*`, `end`),
   - required contracts per action,
   - security-critical scope and filters,
   - default action configuration.

2) **Dynamic runtime input is allowed only through controlled message passing**:
   - model may emit optional directives,
   - `inbox_dispatcher` validates and enqueues only allowlisted directives,
   - consuming actions may apply those directives as optional overrides.

3) **Routing and directive distribution are explicitly separated**:
   - `json_decision_router` decides next step id from decision keys (`decision`/`route`/`mode`),
   - `inbox_dispatcher` only performs dynamic configuration dispatch,
   - neither action should assume the other role.

4) **Fail-safe fallback behavior is mandatory**:
   - invalid or unknown directives are ignored,
   - absence of valid directive means action uses static YAML defaults,
   - pipeline remains executable without dynamic directives.

## Non-negotiable invariants

1) **Topology integrity**
- Dynamic directives must never create/remove/rewire pipeline steps.
- Next-step control remains explicit in pipeline and router actions.

2) **Scoped dynamic power**
- A directive is accepted only if `target_step_id` exists in `inbox_dispatcher.rules`.
- Only `allow_keys` for that target may pass.
- Optional `rename` is explicit and local to the target rule.

3) **Security boundary preservation**
- Dynamic directives must not override security-critical retrieval scope (repository/snapshot/ACL/classification contracts).
- Security filters remain governed by base runtime/pipeline contracts.

4) **Deterministic message lifecycle**
- Inbox is per-run, memory-only.
- Messages are addressed by exact `target_step_id`.
- Messages are consumed on step entry (consume-once semantics).

## Implementation notes (normative)

1) **Recommended sequence for router-driven phases**
- `call_model_*` emits one JSON object (decision + optional `dispatch`),
- `inbox_dispatcher` parses and enqueues allowed directives,
- `json_decision_router` resolves flow branch,
- downstream actions consume only their own inbox messages.

2) **Directive schema contract**
- Preferred target key: `target_step_id` (aliases `target` / `id` allowed),
- `topic` is an action-level message label (not an address),
- dynamic payload keys are filtered by allowlist per target step.

3) **Defaulting rule for `topic`**
- `dispatch[].topic` if present,
- else `rules.<target>.topic`,
- else `"config"`.

4) **Observability**
- Keep ENQUEUE/CONSUME trace visibility enabled for debugging and audits.
- Troubleshooting should always answer: who sent what, to which step, and what was consumed.

## Alternatives considered

1) **Static-only configuration (reject dynamic directives)**
- Pros: maximum determinism and simplicity.
- Cons: poor adaptability, larger YAML branching footprint, slower experimentation.

2) **Fully model-driven runtime (dynamic topology and parameters)**
- Pros: maximum flexibility.
- Cons: reduced safety, weak change auditability, high risk of hidden regressions.

3) **Direct state mutation from model payload (no dispatcher/allowlist)**
- Pros: minimal plumbing.
- Cons: no per-target guardrails, blurred ownership, high security/correctness risk.

We choose controlled dynamic directives because it preserves static architecture guarantees while enabling bounded runtime adaptation.

## Consequences

### Positive
- Better balance of stability and flexibility.
- Safer runtime tuning via allowlisted directives.
- Clear separation of concerns between flow routing and parameter dispatch.
- Improved debugability with explicit message traces.

### Negative / costs
- Additional conceptual layer (inbox messaging + rules).
- Contract maintenance overhead (allowlists, renames, action consumers).
- Need for stronger scenario tests to prevent drift between prompt output and dispatcher rules.

## Rollout / verification

1) Keep static defaults complete so pipeline is valid without any dynamic directives.  
2) Add dynamic directives only for optional knobs, never for security-critical fields.  
3) Cover with tests:
- accepted directive path,
- rejected unknown target/key path,
- fallback to static defaults when no directive is accepted,
- trace visibility of ENQUEUE/CONSUME events.

## Open questions

- Should retrieval planning eventually move to a first-class inbox message contract (single `retrieval_plan`) to reduce repeated parsing across actions?
- Which dynamic knobs justify promotion to static YAML defaults after enough production evidence?
