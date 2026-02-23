# ADR-0008: Pipeline behavior freeze via compat lockfile

- **Status:** Accepted  
- **Date:** 2026-02-22  
- **Decision maker:** Roland (architecture owner for LocalAI-RAG)  
- **Related:** ADR-0002 (Design by Contract for YAML pipelines), ADR-0007 (Static pipeline config + dynamic runtime directives)

## Context

We need to guarantee that upgrading the engine (e.g. `0.3.0`) does **not** change the semantics of a pipeline written for `0.2.0` without an explicit user migration.

YAML pipelines describe intent and configuration, but they do **not** pin all implicit behavior (defaults, normalization, validation).

Therefore, a separate mechanism is required to freeze runtime behavior across engine versions.

## Decision

We introduce a **compat/lockfile-based behavior freeze** with strict fail-fast rules.

### 1) Mandatory YAML settings

Every pipeline YAML must include:

- `settings.behavior_version: "0.2.0"` (string)
- `settings.compat_mode: locked|latest|strict`

Fail-fast rules:
- missing `behavior_version` → error
- unknown `compat_mode` → error
- `compat_mode: locked` without lockfile → error

### 2) Default runtime policy

- **Production:** `compat_mode: locked` (stability > convenience)
- **Dev/Test:** `compat_mode: latest` allowed, but `behavior_version` is still required

### 3) Lockfile role and minimum contents

Lockfile freezes semantics by pinning:

- `behavior_version`
- per `action_id`: `behavior` (e.g. `"0.2.0"`)
- **resolved defaults** that otherwise come from code

Lockfile is versioned in the client repo.

### 4) Lockfile name and location

Default rule:

- lockfile is **next to the YAML**
- name: `<pipeline_basename>.lock.json`

We intentionally **avoid** `lockfile_path` fields in YAML to reduce footguns and preserve portability.  
Optional overrides are tooling-only (CLI), not part of the default contract.

### 5) Locked runtime is real (not declarative)

In `compat_mode: locked`, the engine:

- loads lockfile
- verifies `behavior_version` match
- builds a **deterministic ExecutionPlan** with resolved params
- uses lockfile as the source of truth for action profiles + defaults

No fallback behavior is allowed.

### 6) Stable `action_id` as contract anchor

`action_id` (e.g. `search_nodes`) is the stable contract key.  
Pipeline refers to `action_id`, and compatibility is realized by selecting an action profile from the lockfile.

### 7) Variant B: legacy pack for old pipelines

If engine `0.3.0+` runs pipelines frozen at `0.2.0`:

- required action profiles must exist in core **or** a legacy pack
- preferred model: legacy pack provides action/profile implementations for `behavior_version: 0.2.0`

### 8) Missing action or profile = hard error

In `compat_mode: locked`:

- missing action or required profile → **hard error**
- system must not auto-switch to `latest`

This prevents silent semantic drift.

### 9) Lockfile generation is mandatory tooling

We provide CLI:

- `pipeline lock <pipeline.yaml>` → `<basename>.lock.json`

`pipeline lock` MUST operate on the **final merged pipeline definition** (after applying `extends`), so the generated lockfile matches the effective runtime pipeline.

Clients **must** generate lockfile before upgrading to any version that changes behavior (e.g. `0.3.0`).

### 10) Minimal tests / quality rules

Required checks:

- deterministic lockfile generation (stable sorting, stable formatting)
- locked without lockfile → error
- `behavior_version` mismatch → error
- missing action/profile → error
- same YAML + lockfile → same ExecutionPlan (resolved params)

### 11) Scope of guarantees

This mechanism guarantees **pipeline/action semantics**.  
It does **not** guarantee identical LLM outputs if model/prompt/LLM parameters change (separate concern).

### 12) Decision IR (runtime decision trace) — optional but recommended

We add an optional **Decision IR** artifact: a stable, implementation-independent record of runtime decisions.

**Purpose**
- Explain and diff behavior across engine versions and migrations (`0.2.0` locked vs `0.3.0` latest).
- Provide auditable evidence of *why* a route/parameter was chosen.
- Enable regression tests: same YAML + lockfile → same decision trace.

**Format**
- `jsonl` (one JSON object per step/decision), deterministic field order when serialized.

**Each entry SHOULD contain**
- `run_id`, `step_id`, `action_id`
- `behavior_version`, `action_behavior`
- `resolved_params` (final parameters used by the action)
- `param_source` (per key: `yaml|settings|lockfile|dispatcher|default`)
- `decision` (e.g., selected route, request built, budget over/ok)
- `next_step_id`
- `ts_utc`

**Compatibility contract**
- In `compat_mode: locked`, the Decision IR for a fixed YAML + lockfile SHOULD be stable (modulo timestamps/run_id).
- Decision IR is **not required** to run pipelines, but is recommended for diagnosing semantic drift and verifying freezes.

**Note**
- Decision IR captures pipeline/action decisions only. LLM outputs may still vary unless the LLM execution profile (model/server/params/prompt hash) is pinned separately.

## Alternatives considered

1) **Only fields in YAML (no lockfile)**  
   Rejected: defaults and normalization would still drift.

2) **Implicit best-effort compatibility**  
   Rejected: hides failures and creates silent semantic changes.

3) **External path override in YAML**  
   Rejected as default: portability and footgun risks.

## Consequences

### Positive
- Strong guarantee: engine upgrades do not silently change semantics.
- Deterministic execution plan with resolved params.
- Explicit migration path for breaking changes.

### Negative / costs
- Requires lockfile generation and versioning.
- More strict validation (may break legacy pipelines).
- Additional maintenance for legacy action profiles.

## Rollout / verification

1) Add required YAML settings (`behavior_version`, `compat_mode`) to all pipelines.  
2) Provide `pipeline lock` CLI and mandate lockfile generation.  
3) Enforce `compat_mode: locked` in production.  
4) Add regression tests for lockfile + locked mode.  
5) Before upgrading to behavior-changing versions, ensure lockfile exists and matches.  
6) (Recommended) Emit Decision IR (`jsonl`) for audit/debug and cross-version diffing.
