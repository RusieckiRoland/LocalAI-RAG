# ADR-0002: Design by Contract for YAML pipelines and model-output routing

- **Status:** Proposed  
- **Date:** 2025-12-22  
- **Decision maker:** Roland (architecture owner for LocalAI-RAG / Indexer)  
- **Related:** ADR-0001 (Canonical node identity for graph-augmented retrieval)

## Context and problem statement

LocalAI-RAG uses YAML-defined pipelines composed of existing actions (e.g., `call_model`, `prefix_router`, `search_nodes`, `expand_dependency_tree`, `fetch_node_texts`, `persist_turn`, etc.).

We already validate basic structural correctness (e.g., `entry_step_id` exists, referenced `next` steps exist). We also run E2E “scenario runner” tests that exercise a handful of standard pipelines.

However, we want stronger guarantees that **arbitrary pipelines authored by others** (still using existing actions) will behave correctly and fail fast when assumptions are violated:

- Prevent “semantically invalid” sequences (e.g., an action that requires `followup_query` running before any action sets it).
- Make routing deterministic and auditable (especially around router prefixes like `[BM25:]`, `[SEMANTIC:]`, etc.).
- Reduce reliance on fragile E2E-only coverage and implicit assumptions in action code.
- Provide clearer error messages and faster debugging when a pipeline is miswired.

## Decision

We adopt **Design by Contract (DbC)** for the pipeline system, implemented as:

1. **Action-level contracts**: each action declares its **Requires / Ensures** (preconditions and postconditions) over `PipelineState` and expected step configuration.
2. **Model Output Contracts** (a specialization of DbC): when `call_model` is used as a router, we define an explicit contract of allowed prefixes and parsing rules; `prefix_router` must be consistent with those definitions.
3. **Two layers of enforcement**:
   - **Static validation (build-time / load-time)**: `PipelineValidator` checks that a pipeline is contract-consistent (ordering, required inputs, existence of routing targets).
   - **Runtime assertions (execution-time)**: actions may assert their `Requires` (fail fast with actionable error messages) and guarantee `Ensures` where feasible.

This strengthens correctness without restricting extensibility: new actions can be added by defining their contracts.

## Rationale

### Why DbC is architecturally preferable

1. **Clear invariants and fail-fast behavior**  
   We turn “tribal knowledge” into explicit, checkable rules with good error messages.

2. **Safer pipeline authoring**  
   People can write new pipelines using existing actions with a much higher confidence that the pipeline is valid before it runs.

3. **Stronger than “tests only”**  
   Scenario tests cover representative paths, but DbC provides systematic safety for new combinations.

4. **Better evolution and refactoring**  
   When an action changes, the contract becomes a compatibility boundary and forces explicit updates.

## Considered alternatives

### Option A: E2E tests only (status quo)
- **Rejected** as primary safety mechanism. E2E scenarios are valuable but cannot exhaustively cover author-defined pipelines.

### Option B: Hard-coded “allowed action order” rules only
- Useful but too rigid and becomes a maintenance burden unless expressed as contracts per action.

### Option C: Full formal state machine with typed states for each step
- Potentially very strong, but significantly more complex and disruptive to the current YAML approach.

DbC provides a strong middle ground: **high leverage** with manageable complexity.

## Consequences

### Pros
- Early detection of invalid pipelines (before running costly retrieval/model calls).
- More deterministic router behavior (prefix parsing + routing consistency).
- Clearer operational debugging: “which precondition failed and why”.
- A scalable framework to add new actions safely.

### Cons / costs
- Requires writing and maintaining contracts for each action.
- Validator logic becomes richer (more rules and diagnostics).
- Runtime assertions need to be carefully designed to avoid noisy failures in non-critical paths.

## Implementation implications (no code)

### 1) Contract schema (conceptual)
For each action, define:
- **requires_state**: which `PipelineState` fields must exist / be non-empty
- **requires_step**: which `step.raw` keys must exist
- **ensures_state**: which `PipelineState` fields are set/modified

Example (conceptual):

- `search_nodes`:
  - Requires: `state.followup_query OR state.retrieval_query` non-empty; `state.retrieval_mode` set to known mode
  - Ensures: `state.context_blocks` updated; `state.seed_nodes` updated (deduped)

- `prefix_router`:
  - Requires: `state.last_model_response` present (router output)
  - Requires: `semantic_prefix`, `bm25_prefix`, ... and matching `on_semantic`, `on_bm25`, ...
  - Ensures: `state.retrieval_mode` set; `state.followup_query` set/trimmed; next step chosen deterministically

### 2) Model Output Contract for routing
When `call_model` is used as a router:
- Define allowed prefixes: `[SEMANTIC:]`, `[BM25:]`, `[HYBRID:]`, `[SEMANTIC_RERANK:]`, `[DIRECT:]`
- Define parse rule: “first matching prefix wins”, normalize whitespace, extract query payload
- Define fallback: unrecognized output → route as `on_other`

### 3) Static validator checks (examples)
- **Ordering checks**: if an action requires `followup_query`, ensure there exists a predecessor that sets it along all paths.
- **Routing consistency**: if a `prefix_router` step defines a prefix, it must define the corresponding `on_*` target; all targets must exist as steps.
- **Router/handler consistency**: if a pipeline uses a known router prompt (e.g., `router_v1`), verify that the `prefix_router` step declares matching prefixes.
- **End conditions**: ensure pipelines end (e.g., `end: true` reachable, or an action that returns `None` has a defined fallback path).

### 4) Runtime assertions (examples)
- If `search_nodes` executes with an empty query → raise a clear error (or optionally return `None` and record diagnostics; policy choice).
- If `prefix_router` has missing `on_*` for a configured prefix → raise “invalid pipeline configuration” immediately.

## Notes

This ADR is deliberately focused on **contracts and validation** for the YAML pipeline layer, not on business logic. It complements ADR-0001 by making the pipeline behavior deterministic and safer to extend: *author pipelines confidently, fail fast when miswired, and keep routing and retrieval behavior explicit.*
