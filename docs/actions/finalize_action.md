# FinalizeAction — purpose and usage

## What it is for

`FinalizeAction` is a pipeline action that **finalizes a turn’s answer**:

1) **Materializes the user-visible output** into `state.final_answer`.
2) Keeps answer fields in a consistent state (`answer_en`, `answer_translated`).
3) (Optionally) performs **persist/logging** side-effects: writes to history and emits an interaction log.

Key rule: `FinalizeAction` is the single place that **sets `state.final_answer`** as the answer shown to the user.

## Where the answer text comes from

`FinalizeAction` is deterministic and follows this priority:

- if `state.answer_translated` is non-empty → `state.final_answer = state.answer_translated`
- otherwise:
  - take `state.last_model_response` (strip)
  - copy it into `state.answer_en`
  - set `state.final_answer = state.answer_en`

So `last_model_response` is treated as “the final model answer” *at the point finalize runs*.

## What it writes to state

Always:

- `state.answer_en` — set to `state.last_model_response` (strip).
- `state.final_answer` — set by priority:
  - `answer_translated` if present,
  - otherwise `answer_en`.

The action **does not translate**. If translation is needed, it should be done earlier (e.g., `translate_out_if_needed`) which populates `state.answer_translated`.

## Persist / logging — optional

`FinalizeAction` can also perform persistence side-effects:

- history write: `runtime.history_manager.set_final_answer(state.answer_en, state.answer_translated)`
- interaction log: `runtime.logger.log_interaction(...)` (question, consultant, branches, and answer)

You can **disable** persistence via a step flag:

- `persist_turn: false`

By default, `persist_turn` is enabled (`true`).

## Step contract (StepDef.raw)

Supported `raw` fields:

- `persist_turn` (bool, optional)
  - `true` (default): write history and emit logs,
  - `false`: skip persistence (useful for tests or dry-runs).

## How to use it in a YAML pipeline

Typical layout:

1) `call_model` produces the output (in `state.last_model_response`).
2) (Optional) `translate_out_if_needed` sets `state.answer_translated`.
3) `finalize` sets `state.final_answer` and (optionally) persists.

Minimal example:

```yaml
- id: call_answer
  action: call_model
  prompt_key: "rejewski/answer_v1"
  next: finalize

- id: finalize
  action: finalize
  end: true
```

Example without persistence (e.g., in tests):

```yaml
- id: finalize
  action: finalize
  persist_turn: false
  end: true
```

### Note about `end: true`

`end: true` marks the step as terminal: the pipeline stops after finalize and the validator does not require `next`.

## Common failure modes

- Running `finalize` when `state.last_model_response` is not the final answer (e.g., it still contains routing or a retrieval query).
- Expecting finalize to translate — it **does not translate**.
- Mismatch between what UI shows (`final_answer`) and what gets logged — hence finalize should be the place that sets `final_answer` and (optionally) persists.

## Minimal checklist when adding finalize to a pipeline

1) Ensure `state.last_model_response` contains the final answer right before finalize.
2) If you want a translated answer, add a translation step earlier to populate `state.answer_translated`.
3) End the turn with `end: true` (or provide `next` if the pipeline continues).
4) In tests, set `persist_turn: false` to avoid side-effects.
