# TranslateInIfNeededAction --- contract and usage (translate_in_if_needed)

Updated: 2026-02-03

## Purpose

`translate_in_if_needed` prepares the user question for the model. If the chat
is in Polish (`translate_chat = true`), it translates the incoming query to
English and stores it in `state.user_question_en`. Otherwise it copies the
original query.

This action is intentionally lightweight and has no side-effects beyond
updating `PipelineState` fields.

## Input

Reads:
- `state.user_query`
- `state.translate_chat`
- `runtime.translator_pl_en` (must provide `.translate(str)`)

Writes:
- `state.user_question_en`

## Step configuration (YAML)

```yaml
- id: maybe_translate_in
  action: translate_in_if_needed
  next: call_model_router
```

No additional step parameters are required.

## Runtime semantics

- If `translate_chat` is true **and** `translator_pl_en.translate` exists:
  - `state.user_question_en = translator_pl_en.translate(state.user_query)`
- Otherwise:
  - `state.user_question_en = state.user_query`

## Notes

- This step never raises on missing translator; it falls back to copy.
- The resulting English question is used later by model prompts.
