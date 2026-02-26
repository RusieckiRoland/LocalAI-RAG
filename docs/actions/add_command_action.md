# AddCommandAction --- contract and usage (add_command_action)

Updated: 2026-02-03

## Purpose

`add_command_action` appends **one or more user-visible command links** to the
final answer text. Commands are permission-gated and resolved by type via the
server-side command registry.

Typical use cases:
- add a "Show Diagram" link if the answer contains PlantUML
- add an "Export to EA (XMI)" link when a diagram exists

## Input

This action reads:
- `PipelineState.allowed_commands` (list of command permissions)
- Answer text fields in priority order:
  - `final_answer`
  - `answer_translated`
  - `answer_neutral`
  - `last_model_response`

## Step configuration (YAML)

### Minimal example

```yaml
- id: add_commands
  action: add_command_action
  commands:
    - type: "showDiagram"
  next: finalize
```

### Multiple commands (single line)

```yaml
- id: add_commands
  action: add_command_action
  commands:
    - type: "showDiagram"
    - type: "ea_export"
  next: finalize
```

### Schema

```yaml
- id: <step_id>
  action: add_command_action
  commands:
    - type: <command_type>  # required, string (e.g., "showDiagram")
```

Validation rules:
- `commands` must be a list.
- Each entry must provide a non-empty `type` string.
- Unknown types are ignored (soft-fail).

## Runtime semantics

1. Resolve base text to append to (priority order):
   - `final_answer` → `answer_translated` → `answer_neutral` → `last_model_response`.
2. For each command type in order:
   - Look up command in registry.
   - Check permission via `state.allowed_commands`.
   - If applicable, generate a link snippet.
3. Append all generated links into a **single line container**:
   `\n\n<div class="command-links">...</div>`
4. Write the updated text back into the same field chosen in step 1.

If no links are generated, the action is a no-op.

**Important:** this action modifies the answer text *before* `finalize`.
Pipelines should keep the `add_command_action` step immediately before
`finalize` to avoid losing appended links.

## Permission model

Commands are gated by `PipelineState.allowed_commands`.
This list is built from group policies (DEV: `security_conf/auth_policies.json`).

Example:
- `showDiagram` requires `allowed_commands` to contain `showDiagram`.
- `ea_export` requires `allowed_commands` to contain `ea_export`.

## Command registry

Commands live in `server/commands` and are registered in:
- `server/commands/registry.py`

The action uses `build_default_command_registry()` to resolve types.

## Output

The action **modifies the answer text** only. It does not create separate
JSON fields. Links are appended as HTML anchors for direct UI rendering.

## Notes

- When a command marks `requires_sanitized_answer`, the answer is normalized
  before appending links (e.g., to ensure stable PlantUML blocks).
- This action is designed to run **before `finalize`**, but works even if
  `final_answer` is already populated.
