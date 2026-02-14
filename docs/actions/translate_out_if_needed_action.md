# TranslateOutIfNeededAction --- contract and usage (translate_out_if_needed)

Updated: 2026-02-13

## Purpose

`translate_out_if_needed` translates the final English answer into Polish when
`translate_chat` is enabled. It populates `state.answer_translated`, which is then used
by `finalize` to select the user-visible output.

## Input

Reads:
- `state.translate_chat`
- `state.answer_en`
- `runtime.markdown_translator` (preferred, supports `.translate_markdown(str)`; may also provide `.translate(str)`)
- `runtime.model` (only when `use_main_model: true`)

Writes:
- `state.answer_translated`

## Step configuration (YAML)

### Default (backward-compatible)

```yaml
- id: maybe_translate_out
  action: translate_out_if_needed
  next: finalize
```

No additional step parameters are required.

### Use main model for translation

When `use_main_model: true` is set, `translate_prompt_key` is required and the action
will call `runtime.model` to perform the translation using the referenced prompt file.

```yaml
- id: translate_out
  action: translate_out_if_needed
  use_main_model: true
  translate_prompt_key: translate_en_pl
  next: finalize
```

## Runtime semantics

- If `translate_chat` is false → no-op.
- If `answer_en` is empty → no-op.
- If `use_main_model` is true:
  - `translate_prompt_key` is required (otherwise the action raises an error).
  - Loads `<prompts_dir>/<translate_prompt_key>.txt` and calls `runtime.model` to translate.
  - `translate_prompt_key` may use Windows separators (`\`); it is normalized to `/` when resolving the prompt file.
  - The action sends `answer_en` as the model input. If the loaded system prompt contains markers
    `<<<MARKDOWN_EN` and `MARKDOWN_EN`, the action wraps the input to match that contract:
    - `<<<MARKDOWN_EN\n{answer_en}\nMARKDOWN_EN`
  - Optional overrides supported (same keys as `call_model`):
    - `native_chat` (if true: calls `model.ask_chat(...)`; else: renders a manual prompt and calls `model.ask(...)`)
    - `prompt_format` (manual prompt mode; default: `codellama_inst_7_34`)
    - `max_tokens` / `max_output_tokens`, `temperature`, `top_k`, `top_p`
- If `runtime.markdown_translator.translate_markdown` is available:
  - `state.answer_translated = translator.translate_markdown(answer_en)`
- Else if `runtime.markdown_translator.translate` is available:
  - `state.answer_translated = translator.translate(answer_en)`
- Otherwise:
  - `state.answer_translated = answer_en` (fallback)

## Tracing

When pipeline tracing is enabled (`RAG_PIPELINE_TRACE=1` or `RAG_PIPELINE_TRACE_FILE=1`), this action logs:
- The rendered prompt (`rendered_prompt`) in manual prompt mode, or the rendered chat payload (`rendered_chat_messages`) in `native_chat` mode (only for `use_main_model: true`).
- The model response (`model_response`, `model_response_len`) when `use_main_model: true`.

## Notes

- This action is intentionally best-effort (translation failures fall back to EN).
- It does not modify `final_answer` directly; `finalize` handles output selection.
