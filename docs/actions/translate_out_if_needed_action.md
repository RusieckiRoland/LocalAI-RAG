# TranslateOutIfNeededAction --- contract and usage (translate_out_if_needed)

Updated: 2026-02-03

## Purpose

`translate_out_if_needed` translates the final English answer into Polish when
`translate_chat` is enabled. It populates `state.answer_translated`, which is then used
by `finalize` to select the user-visible output.

## Input

Reads:
- `state.translate_chat`
- `state.answer_en`
- `runtime.markdown_translator` (preferred, supports `.translate_markdown(str)`; may also provide `.translate(str)`)

Writes:
- `state.answer_translated`

## Step configuration (YAML)

```yaml
- id: maybe_translate_out
  action: translate_out_if_needed
  next: finalize
```

No additional step parameters are required.

## Runtime semantics

- If `translate_chat` is false → no-op.
- If `answer_en` is empty → no-op.
- If `runtime.markdown_translator.translate_markdown` is available:
  - `state.answer_translated = translator.translate_markdown(answer_en)`
- Else if `runtime.markdown_translator.translate` is available:
  - `state.answer_translated = translator.translate(answer_en)`
- Otherwise:
  - `state.answer_translated = answer_en` (fallback)

## Notes

- This action is intentionally best-effort (translation failures fall back to EN).
- It does not modify `final_answer` directly; `finalize` handles output selection.
