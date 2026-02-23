# `load_conversation_history`

## Purpose
`load_conversation_history` loads previous conversation history and prepares it for prompt injection.

Preferred source:
- `runtime.conversation_history_service` (new contract)

Legacy fallback:
- `runtime.history_manager` (older HistoryManager API)

## Input
Reads:
- `state.session_id`
- `runtime.conversation_history_service.get_recent_qa_neutral(...)` (if available)
- otherwise `runtime.history_manager.get_context_blocks()` (legacy)

Writes:
- `state.history_qa_neutral` (`Dict[question_neutral, answer_neutral]`)
- `state.history_dialog` (Dialog: `[{role, content}, ...]`, neutral-only)
- `state.history_blocks` (legacy human-readable blocks)

## Runtime behavior
- Best-effort: history load failures do **not** stop the pipeline.
- On error, history fields are set to empty values.

## Step configuration (YAML)
```yaml
- id: load_history
  action: load_conversation_history
  # Optional (default: 30)
  history_limit: 30
  next: call_model_router
```
