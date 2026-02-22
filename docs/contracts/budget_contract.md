# Budget Contract (Pipeline + Model Limits)

This document defines the **token budget contract** between:
- model configuration (`config.json`),
- pipeline settings (`pipelines/*.yaml` → `settings`),
- `call_model` steps (per‑step generation limits),
- retrieval/context budgeting (`max_context_tokens`, `manage_context_budget`),
- chat history (`max_history_tokens`).

Goal: **prevent** `prompt_tokens + max_output_tokens > model_context_window`, which causes runtime errors.

---

## Terminology

- `model_context_window` (`n_ctx`)  
  Maximum tokens the model can handle (prompt + generation).  
  Source: `config.json["model_context_window"]`.

- `max_output_tokens` (per `call_model` step)  
  Maximum generation length for a step.  
  Sources (precedence):
  1) YAML step: `max_output_tokens`
  2) YAML step: `max_tokens`
  3) fallback: `config.json["model_max_tokens"]`

- `max_context_tokens` (pipeline context budget)  
  Budget for retrieval context (`state.context_blocks`).  
  Source: `settings.max_context_tokens`.

- `max_history_tokens` (history budget)  
  Budget for `state.history_dialog` when `use_history: true`.  
  Source: `settings.max_history_tokens`.

- `budget_safety_margin_tokens`  
  Safety margin subtracted from the usable budget.  
  Source: `settings.budget_safety_margin_tokens` (default: 128).

---

## Contract inequality

For each `call_model` step:

```
fixed_prompt_tokens(step)
+ max_history_tokens
+ max_context_tokens
+ max_output_tokens(step)
+ safety_margin
<= model_context_window
```

`fixed_prompt_tokens(step)` includes:
- system prompt (`prompt_key`),
- `user_parts.template` wrappers (measured with empty `{}`),
- format overhead (roles, separators).

Note: retrieval (`state.node_texts`) is materialized into `state.context_blocks`, so it is governed by `max_context_tokens`.

---

## Policy (fail‑fast by default)

**Production must be fail‑fast.** Any missing or invalid configuration must raise an error.

### Allowed policies
- `fail_fast` (default and required for production)
- `auto_clamp` (allowed only in dev/test or when explicitly enabled)

### Enabling auto‑clamp
Auto‑clamp is **not** allowed by default in production. If you want it:
- set `PIPELINE_LIMITS_POLICY=auto_clamp`, or
- add an explicit config flag (e.g., `allow_auto_clamp: true`) and document it.

---

## Validation rules (always enforced)

- `settings.max_context_tokens` must exist and be `int > 0`.
- `model_context_window` must exist and be `int > 0`.
- If any `call_model` step has `use_history: true`, then `settings.max_history_tokens` must be present and `>= 0`.

If any required value is missing:
- **fail_fast**: raise an error and stop execution.
- **auto_clamp**: still raise an error for missing required fields (no silent defaults).

---

## Auto‑clamp behavior (when explicitly enabled)

Auto‑clamp applies **in‑memory only** for the current request; it does not modify YAML.

Possible clamps:
- Reduce `settings.max_context_tokens` if the worst‑case step exceeds the model window.
- Reduce per‑step `max_output_tokens` if still over budget.

Every clamp must log a warning with before/after values and reason.

---

## Cache / performance

Budget calculations are recomputed only when inputs change. Fingerprint includes:
- pipeline YAML + all `extends` files,
- prompt files used by `call_model` steps.

---

## History trimming

If `use_history: true` and `max_history_tokens` is configured,
`call_model` trims `state.history_dialog` from oldest entries until the budget fits.

---

## Recommended configuration

1) Set a realistic `model_context_window` (e.g., 9600, 16384).
2) In pipeline settings:
   - `max_context_tokens` ~60–70% of the window
   - `max_history_tokens` ~10–15%
   - per‑step `max_output_tokens` (smaller for routers, larger for answer/summarizer)
   - `budget_safety_margin_tokens` 128–256
3) Keep production on `fail_fast`; allow `auto_clamp` only with explicit opt‑in.
