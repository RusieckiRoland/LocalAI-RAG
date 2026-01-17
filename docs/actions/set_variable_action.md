# SetVariablesAction --- contract and usage (set_variables)

Updated: 2026-01-13

## Purpose

`set_variables` is a pipeline step used **only to assign / map fields on
`PipelineState`**. It is equivalent to CI/CD systems "set variables":
simple, sequential, no business logic and no implicit behavior.

Typical use cases: - copying values between state fields, - clearing
fields before the next stage, - simple transformations (split lines,
parse JSON), - promoting model output into `context_blocks` before the
next model call.

## Input

The action has **no logical inputs of its own** --- it reads only from
`state` fields referenced by `from`.

## Step configuration (YAML)

A `set_variables` step **must** define `rules` as a non-empty list.

### Minimal example

``` yaml
- id: promote_summary
  action: set_variables
  rules:
    - set: context_blocks
      from: last_model_response
      transform: to_context_blocks
```

### Full schema

``` yaml
- id: <step_id>
  action: set_variables
  rules:
    - set: <destination_field>      # required, string
      from: <source_field>          # optional (required if value not provided), string
      value: <literal_yaml_value>   # optional (mutually exclusive with from), any YAML literal
      transform: <transform_name>   # optional, default: copy
```

### Validation rules (fail-fast)

For the whole step: - `rules` must exist, - `rules` must be a list, -
`rules` must not be empty.

For each rule: - `set` must exist and be a non-empty string, - exactly
**one of**: - `from` (non-empty string), - `value` (any YAML literal), -
`set` and `from` **must not contain dots** (`.`) --- no dot-paths in
v1, - `transform` (if present) must be in the allowlist.

Conflicts: - `from` + `value` together → error, - missing both `from`
and `value` → error.

## Runtime semantics

-   Rules are executed **sequentially**, in YAML order.
-   For each rule:
    1)  input value is obtained:
        -   from `value`, or
        -   from `getattr(state, from)`,
    2)  `transform` is applied (or `copy`),
    3)  result is written via `setattr(state, set, output)`.

If any rule fails, the step stops and **subsequent rules are not
executed**.

## Supported transforms (v1)

Allowlist:

-   `copy` (default)
-   `to_list`
-   `split_lines`
-   `parse_json`
-   `to_context_blocks`
-   `clear`

### copy

-   output = input (no change)

### to_list

Convert to list: - `None` → `[]` - `list` → unchanged - `str` → `[str]`,
but if `str.strip()` is empty → `[]` - other types → error

### split_lines

-   `None` → `[]`
-   `str` → `splitlines()` + `strip()` each line + drop empty
-   other types → error

### parse_json

-   `str` → `json.loads(str)`
-   parse error → step error (fail-fast)
-   other types → error

### to_context_blocks

Normalizes to the format used in this repo:

-   output is always: `List[str]` (compatible with
    `PipelineState.context_blocks`)

Rules: - `None` → `[]` - `str` → if non-empty → `[str]` - `list[str]` →
strip + drop empty - `list[dict]` → each element must have
`"text": str` - `text` is stripped - empty entries are dropped - other
types → error

Purpose: - promote `last_model_response` → `context_blocks` - normalize
retrieval / summary outputs

### clear

Shortcut for clearing destination field based on its current type: - if
field is `list` → `[]` - `dict` → `{}` - `str` → `""` - other / missing
→ `None`

If you need full determinism, **use `value:` instead of `clear`**.

## Clearing fields --- recommended way

Deterministic:

``` yaml
- id: clear_context
  action: set_variables
  rules:
    - set: context_blocks
      value: []
```

``` yaml
- id: clear_last_response
  action: set_variables
  rules:
    - set: last_model_response
      value: null
```

## Example with multiple rules in one step

``` yaml
- id: parse_filter_and_clear_context
  action: set_variables
  rules:
    - set: retrieval_filters
      from: router_raw
      transform: parse_json
    - set: context_blocks
      value: []
  next: search_nodes
```

This is the recommended style when you want to "prepare state" before
the next step.

## Outputs

The action does **not return next step id** --- it relies on `next`
defined in YAML. It only modifies `PipelineState` fields listed in
`set`.

## Checklist for pipeline authors

1)  Ensure every `from` refers to an existing `PipelineState` field.
2)  Do not use dot-paths (`a.b.c`) --- forbidden in v1.
3)  Prefer `value:` over `clear` when clearing fields.
4)  Do not put decision logic here --- this step is only for state
    mapping.
5)  If multiple assignments must happen together before the next step,
    keep them in one `set_variables` step.
