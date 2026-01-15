# Test Structure and Failure Map

This document describes how tests in the repository are organized, what each group is responsible for, and which tests are expected to fail when specific parts of the pipeline contract change.

The goal is to make test failures predictable and actionable, especially during pipeline refactors.


## 1. Test Layers Overview

Tests are intentionally split into layers, each with a different stability and responsibility level:

1. **Unit / Action-level tests**
2. **Focused E2E tests**
3. **Scenario-based pipeline tests (currently skipped)**

These layers are not equal in terms of expected churn.


## 2. Unit / Action-Level Tests

**Location (examples):**
- `tests/pipeline/actions/`
- `tests/pipeline/test_fetch_more_context_*.py`
- `tests/pipeline/test_prefix_router_*.py`
- `tests/pipeline/test_call_model_*.py`

**Purpose:**
- Validate *strict contracts* of individual pipeline actions.
- Ensure actions fail fast and deterministically on invalid input.
- Protect against silent regressions in parsing, routing, and state mutation.

**What they cover:**
- Required YAML fields (e.g. `search_type`, `routes`, `user_parts`)
- Input/output normalization
- State mutations (`retrieval_mode`, `context_blocks`, `seed_nodes`)
- Edge cases (empty payloads, duplicates, missing IDs)

**What will break these tests:**
- Changing an action’s YAML contract
- Renaming/removing required state fields
- Relaxing or tightening validation rules

**Expected stability:**
- Medium churn during refactors
- High stability once the action contract is frozen

These tests should be updated **immediately** when an action contract changes.


## 3. Focused E2E Tests

**Location (examples):**
- `tests/e2e/test_e2e_smoke.py`
- `tests/e2e/test_e2e_advanced.py`

**Purpose:**
- Verify that a *small, known pipeline* runs end-to-end.
- Catch integration issues between actions.
- Validate minimal real-world execution paths.

**What they cover:**
- Engine step execution order
- Interaction between router → fetch → answer
- History loading, budget checks, finalization
- Minimal model / retriever interaction

**What will break these tests:**
- Breaking changes in:
  - `call_model` invocation semantics
  - `prefix_router` routing rules
  - Fetch/search dispatch rules
- Engine-level changes (looping, guards, termination)

**Expected stability:**
- Should mostly survive action-level refactors
- Fail when integration semantics change

These tests act as **early warning signals**, not full regression coverage.


## 4. Scenario-Based Pipeline Tests (Skipped)

**Location:**
- Scenario runner test (JSON-driven)
- Pipeline scenarios defined in `pipeline_scenarios.json`

**Purpose:**
- Validate many realistic pipelines and execution paths.
- Act as long-term regression coverage for the *final* pipeline design.

**Current status:**
- Explicitly skipped.

**Reason:**
- Scenario tests encode assumptions about:
  - YAML structure
  - Routing semantics
  - Follow-up behavior
  - Search / graph interaction order

While the pipeline contract is still evolving, these assumptions are unstable and cause noisy failures.

**What will break them:**
- Almost any pipeline-level refactor
- Contract tightening
- Changes in fallback or guard behavior

**Expected stability:**
- Low during development
- High only after pipeline contracts are finalized

These tests should be re-enabled **only after** the pipeline contract is considered stable.


## 5. Failure Prediction Map

| Change Type | Expected Failures |
|------------|------------------|
| Action YAML contract change | Unit / action tests |
| State field rename/removal | Unit + focused E2E |
| Routing logic change | Focused E2E |
| Engine loop / guard logic | Focused E2E |
| Pipeline YAML redesign | Scenario tests |
| Model invocation semantics | E2E + fakes |

This mapping is intentional and helps distinguish **expected breakage** from real regressions.


## 6. Recommended Workflow During Refactors

1. Modify pipeline / action contracts.
2. Immediately update:
   - Unit tests
   - Action fakes/mocks
3. Ensure focused E2E tests pass.
4. Keep scenario tests skipped.
5. Once contracts stabilize:
   - Update scenario definitions
   - Re-enable scenario runner


## 7. Key Principle

Not all test failures mean regressions.

During active pipeline development:
- **Unit tests** enforce correctness.
- **Focused E2E tests** protect integration.
- **Scenario tests** are deferred until the system design stops moving.

This separation is deliberate and should be preserved.
