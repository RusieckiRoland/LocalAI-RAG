# `call_model` (EN)

## Purpose
`call_model` is a pipeline action that **invokes the LLM**.

After the model call:
- the model output text is stored in `state.last_model_response`.

If the YAML step defines `next`, the pipeline **continues to the step specified by `next`**.

---

## `prompt_key` and prompt files
`prompt_key` points to a text file that contains the **system prompt**.

The action loads the system prompt from:
- `prompts_dir/<prompt_key>.txt`

Example:
- `prompts_dir = "prompts"`
- `prompt_key = "rejewski/context_summarizer_v1"`  
→ file: `prompts/rejewski/context_summarizer_v1.txt`

`prompt_key` may include **subfolders** (e.g. `e2e/router_v1`). The `.txt` extension is appended automatically.

Missing file → **fail-fast**:
- `ValueError: call_model: system prompt file not found: ...`

---

## Two model invocation modes

### 1) `native_chat: true` (chat/messages mode)
In this mode, **the model client/library formats chat messages**. The pipeline provides:
- the system prompt (from the file referenced by `prompt_key`),
- the user message content assembled from `user_parts`,
- optional conversation history (when `use_history: true`).

In this mode the action calls: `model.ask_chat(...)` (the model client must implement it).

Conceptually, the model receives:
- `system_prompt` → `system` role
- `user_part` → `user` role (assembled from `user_parts`)
- `history` → earlier messages (only when `use_history: true`)

### 2) Manual mode (`native_chat` omitted or `false`)
In this mode, the pipeline **builds a final prompt string** (e.g. `[INST] ...`) and calls `model.ask(prompt=...)`.

Manual prompt building is controlled by:
- `prompt_format`

Currently implemented format:
- `codellama_inst_7_34` (CodeLlama Instruct 7B/34B)

Builder selection is delegated to:
- `get_prompt_builder_by_prompt_format(prompt_format)`

Unknown `prompt_format` → **fail-fast** in the factory (English error message).

---

## `use_history` — when history is included
History is **not included automatically**.

To include history:
- set `use_history: true`

Then `call_model` reads history from `state.history_dialog` and passes it to:
- `model.ask_chat(...)` (when `native_chat: true`), or
- the prompt builder (manual mode).

---

## `user_parts` — how user content (`user_part`) is assembled
`call_model` is YAML-driven: `user_parts` defines:
- where to read data from `state`,
- how to wrap it (a template with `{}`).

In YAML you define:
- `user_parts.<name>.source` — a `state` attribute/method name (if it’s a method, it will be called),
- `user_parts.<name>.template` — a format string that contains `{}`.

Fail-fast rules:
1) `user_parts` must exist and must not be empty,
2) each `template` must contain `{}`,
3) each `source` must be a non-empty string and must reference an existing `state` attribute/method.

Result:
- each `user_parts.<name>` becomes: `template.format(text)`,
- `user_part` is the concatenation of all parts in the order defined in YAML.

### Example (context summarization)
```yaml
- id: call_model_summarize_context
  action: call_model
  prompt_key: "rejewski/context_summarizer_v1"
  use_history: true
  user_parts:
    evidence:
      source: context_blocks
      template: "### Evidence:\n{}\n\n"
    user_question:
      source: user_question_en
      template: "### User:\n{}\n\n"
  next: call_model_answer
```

Meaning:
- system prompt: `prompts/rejewski/context_summarizer_v1.txt`
- `user_part`:
  - `evidence` ← `state.context_blocks` wrapped as `### Evidence:`
  - `user_question` ← `state.user_question_en` wrapped as `### User:`
- history (because `use_history: true`) ← `state.history_dialog`
- model output → `state.last_model_response`
- after the step completes, the pipeline continues to `next: call_model_answer`

---

## Generation parameters (overrides) and default values
`call_model` may optionally pass:
- `max_tokens`
- `max_output_tokens`
- `temperature`
- `top_k`
- `top_p`

If a parameter is not provided in YAML, `call_model` **does not override** it.

Notes:
- `max_output_tokens` is an explicit alias for the model output length limit. It maps to the model client parameter `max_tokens`.
- If both `max_output_tokens` and `max_tokens` are provided, `max_output_tokens` **wins**.

**Default values in the repo’s default `Model` implementation:**
- `max_tokens = 1500`
- `temperature = 0.1`
- `top_k = 40`
- `top_p = None` (unset)
- (for completeness: `repeat_penalty = 1.2` — not overridden by `call_model`)

If you replace the model client, defaults may differ.

---

## Debugging: how to see what was sent to the model
Enable detailed pipeline trace logging in `.env`:

```env
# === Only for debugging the pipeline; creates one JSON per user query
RAG_PIPELINE_TRACE_FILE=1
RAG_PIPELINE_TRACE_DIR=log/pipeline_traces
```

In the trace you will see:
- manual mode: `rendered_prompt`
- `native_chat: true` mode: `rendered_chat_messages` (messages payload)

For convenient viewing in VS Code, use:
- https://github.com/RusieckiRoland/rag-debug-toolkit.git

---

## Working with `PrefixRouterAction` (routing by response prefix)
A very common pipeline pattern is:

1) `call_model` invokes the model and stores the output in `state.last_model_response`.
2) The next pipeline step is `PrefixRouterAction`, which reads `state.last_model_response`, matches a prefix, and selects the next path.

Examples:
- Model returns: `[DIRECT:] ...`, `[BM25:] ...`, `[SEMANTIC:] ...` → `PrefixRouterAction` routes the pipeline to the corresponding step.
- Model returns: `[Answer:] ...` or `[Requesting data on:] ...` → `PrefixRouterAction` decides whether to finish (`finalize`) or to enter a loop (follow-up / loop guard).

In this setup:
- `call_model` always **produces an output** and writes it into `state.last_model_response`,
- the execution path choice is made by the **next step** (e.g. `PrefixRouterAction`).

---

## Security (important)

### 1) `native_chat: true` and strict system/user separation
In `native_chat: true` mode, the **system prompt** is passed as a dedicated input (`system_prompt`),
and the user content as a separate input (`user_part`).

Even so, you must enforce **input hygiene** for `user_part`, so a user cannot “smuggle” symbols/tokens that effectively alter the intended prompt behavior
(e.g., by injecting pseudo-markup / a mini-DSL that your library or logging/viewer might treat specially).

In practice:
- treat `user_part` as **untrusted input**,
- normalize/filter control symbols/tokens according to your application policy,
- never allow `user_part` to influence **what the system prompt is** (system prompt must always come from `prompt_key` / file).

> Note: the exact filtering/escaping strategy is the application’s responsibility.
> The key rule is: **the system prompt is fixed and controlled by the application**, not by the user.

### 2) Retrieval access policy — never rely on the model
The LLM must **never be the source of truth** for retrieval access policy (permissions, tenant/group constraints, security tags, filters).

Rule:
- enforce access control and filters **inside retrieval** (in code, before fetching any data),
- the model may suggest a query, but it does not decide what is allowed to be retrieved,
- do not “ask the model” whether it is allowed to see data — that must come from hard backend rules.

This is critical for both security and deterministic system behavior.

> **Note (escape/hardening):** In manual mode (`prompt_format: codellama_inst_7_34`), the CodeLlama builder applies basic escaping/hardening specific to the `[INST]` prompt structure (to keep the prompt well-formed).  
> In `native_chat: true` mode, for this kind of escaping you **fully rely on the model client/library** — **do not assume** it matches the CodeLlama builder behavior.  
> **Requirement:** before using `native_chat: true`, verify (for the exact client and its version) what escaping/sanitization is actually applied, and enforce it in the application if needed.
