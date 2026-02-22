# Pipeline settings, inheritance, and overrides

This document focuses on **pipeline-level settings**, **inheritance**, and **override rules**.  
It intentionally does not describe action-specific fields.

## 1) Pipeline structure (minimal form)

```yaml
YAMLpipeline:
  name: my_pipeline

  settings:
    entry_step_id: start
    behavior_version: "0.2.0"
    compat_mode: locked

  steps:
    - id: start
      action: translate_in_if_needed
      next: finalize

    - id: finalize
      action: finalize
      end: true
```

Notes:
- `YAMLpipeline` is the required root key for a single pipeline.
- `pipelines` / `YAMLpipelines` is supported for multi‑pipeline files.

## 2) Required settings (fail‑fast)

The following fields **must** exist in `settings`:

- `entry_step_id` — the starting step ID.
- `behavior_version` — pipeline behavior version string.
- `compat_mode` — one of `locked`, `latest`, `strict`.

Fail‑fast rules:
- missing `behavior_version` → error
- unknown `compat_mode` → error
- `compat_mode: locked` without lockfile → error

## 3) Compatibility + lockfile

When `compat_mode: locked`, a lockfile must exist **next to the YAML**:

```
<pipeline_basename>.lock.json
```

Lockfile freezes behavior by pinning:
- pipeline `behavior_version`
- per‑action `behavior`
- resolved defaults that would otherwise come from code

Generate a lockfile:

```bash
python -m code_query_engine.pipeline.pipeline_cli lock path/to/pipeline.yaml
```

## 4) Inheritance with `extends`

`extends` lets a pipeline reuse and override another pipeline:

```yaml
YAMLpipeline:
  name: child
  extends: ./base/base_pipeline.yaml

  settings:
    max_history_tokens: 250

  steps:
    - id: search
      action: search_nodes
```

### Merge rules (current loader behavior)

- **Settings** are deep‑merged (child overrides parent).
- **Steps** are merged by `id`:
  - if child defines a step with the same `id`, its fields override parent step fields,
  - new child steps are appended in child order.
- `extends` chains are resolved recursively; cycles are rejected.

### Important consequences

- Any setting defined in a parent **can be overridden** by the child.
- Any setting defined only in the parent **will be inherited**.
- A child can override **only a subset** of step fields (no need to redefine the whole step).

## 5) What is considered “pipeline settings”

`settings` are **pipeline‑level defaults and configuration**, typically used by actions via runtime settings.  
Examples you can define (non‑exhaustive, pipeline‑level only):

- Retrieval scope and data: `snapshot_set_id`, `snapshot_id`, `snapshot_id_b`, `repository`.
- Budgeting: `max_context_tokens`, `max_history_tokens`, `budget_safety_margin_tokens`.
- History: `history_summarization_policy`.
- Graph defaults: `graph_max_depth`, `graph_max_nodes`, `graph_edge_allowlist`.
- UI/callback visibility: `callback`, `stages_visibility`.
- `prompts_dir` — location of prompt files used by the pipeline.
- Translation toggles or model config keys used by runtime.

If a setting exists in both parent and child, **the child wins**.

## 6) Override priority (settings vs steps)

General rule:

1. Step‑level fields override settings for that step.
2. Settings provide defaults when a step omits a field.

This rule applies only to fields that an action explicitly resolves from settings.  
If an action does **not** read a setting, the setting has no effect.

## 7) When a pipeline can override defaults

You can override defaults in three ways:

1. **Settings override** — change pipeline‑level defaults (applies to many steps).
2. **Step override** — set a field directly on a step (highest priority for that step).
3. **Child override via `extends`** — override parent settings and/or step fields.

In `compat_mode: locked`, lockfile defaults also participate in resolution and are applied **before** settings/step fields (deterministic resolved params).

## 8) Multi‑pipeline files

A single YAML file can define multiple pipelines:

```yaml
YAMLpipelines:
  - name: p1
    settings: { ... }
    steps: [ ... ]
  - name: p2
    settings: { ... }
    steps: [ ... ]
```

The loader selects the pipeline by `name` when `pipeline_name` is provided.

## 9) Pipeline‑level validation (summary)

The validator enforces:
- required settings (`entry_step_id`, `behavior_version`, `compat_mode`)
- unique step IDs
- `entry_step_id` references an existing step
- actions are known IDs

Action‑specific validations are handled elsewhere and are not described here.
