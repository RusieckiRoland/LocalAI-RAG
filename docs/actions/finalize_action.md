# `finalize`

## Purpose
`finalize` materializes the user-visible answer into `state.final_answer` and optionally persists/logs the turn.

This action is the only place that should decide the final output shown to the user.

## Final answer selection (exact behavior)
`finalize` reads:
- `state.answer_neutral`
- `state.answer_translated`
- `state.banner_neutral`
- `state.banner_translated`
- `state.translate_chat`

Rules:
- if `translate_chat == true`:
  - with banner: `final_answer = banner_translated + "\\n\\n" + answer_translated`
  - without banner: `final_answer = answer_translated`
- if `translate_chat == false`:
  - with banner: `final_answer = banner_neutral + "\\n\\n" + answer_neutral`
  - without banner: `final_answer = answer_neutral`

`finalize` does not translate and does not fall back to `last_model_response`.

## Persistence/logging side effects
By default `finalize` persists the turn (`persist_turn: true`).

When persistence is enabled:
- logs interaction via `runtime.logger.log_interaction(...)` (best effort),
- writes conversation turn via `runtime.conversation_history_service` (best effort).

History write uses the user-visible output:
- when `translate_chat == true`, persisted `answer_translated` is `final_answer`,
- when `translate_chat == false`, persisted `answer_neutral` is `final_answer`.

## Step config
Supported `raw` fields:
- `persist_turn: bool` (optional, default `true`)

## Typical YAML usage
```yaml
- id: set_answer
  action: set_variables
  variables:
    answer_neutral:
      from: last_model_response
  next: translate_out

- id: translate_out
  action: translate_out_if_needed
  next: finalize

- id: finalize
  action: finalize
  persist_turn: true
  end: true
```

Example without persistence:
```yaml
- id: finalize
  action: finalize
  persist_turn: false
  end: true
```

## Minimal checklist
1. Ensure upstream steps set `answer_neutral`.
2. If `translate_chat` is enabled, ensure upstream steps set `answer_translated`.
3. If you use `custom_banner` in `call_model`, confirm the matching banner field is present before `finalize`.
