# `load_conversation_history`

## Purpose
`load_conversation_history` loads previous conversation context from `runtime.history_manager`
and stores it on `state.history_blocks` so it can be included in prompts later.

## Input
Reads:
- `state.session_id`
- `runtime.history_manager.get_context_blocks()`

Writes:
- `state.history_blocks` (list of strings)

## Runtime behavior
- Best-effort: history load failures do **not** stop the pipeline.
- On error, `state.history_blocks` is set to an empty list.

## Step configuration (YAML)
```yaml
- id: load_history
  action: load_conversation_history
  next: call_model_router
```

