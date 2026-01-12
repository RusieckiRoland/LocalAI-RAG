# `call_model` (EN)

## Purpose
`call_model` is the **main action of the entire pipeline** — it **invokes the LLM**.

After the model call, the output is stored in:
- `state.last_model_response`

The step returns `next` (when configured in YAML) so the pipeline can continue.

---

## `prompt_key` and prompt files
`prompt_key` points to a text file containing the **system prompt**.

The action loads the system prompt from:
- `prompts_dir/<prompt_key>.txt`

Example:
- `prompts_dir = "prompts"`
- `prompt_key = "rejewski/context_summarizer_v1"`
→ file: `prompts/rejewski/context_summarizer_v1.txt`

`prompt_key` may include folders (e.g. `e2e/router_v1`). The `.txt` extension is appended automatically.

Missing file → **fail-fast**:
- `ValueError: call_model: system prompt file not found: ...`

---

## Two model invocation modes

### 1) `native_chat: true` (native chat mode)
In this mode, **the library formats chat messages** (chat/messages). The pipeline provides:
- the user message content (it may include a `### Evidence:` section — i.e. retrieval context),
- the system prompt (from `prompt_key`),
- optional conversation history.

In this mode the action calls: `model.ask_chat(...)` (the model must implement it).

Conceptually, the model receives:
- `system_prompt` → `system` role
- `user_part` → `user` role (assembled from `inputs/prefixes`)
- `history` → prior turns (optional; only when `use_history: true`)

### 2) Manual mode (`native_chat` omitted or `false`)
In this mode, the pipeline **builds the full prompt string** (e.g. `[INST] ...`) and calls `model.ask(prompt=...)`.

Manual prompt building is controlled by:
- `prompt_format`

Currently implemented manual prompt format:
- `codellama_inst_7_34` (CodeLlama Instruct 7B/34B)

Builder selection is delegated to:
- `get_prompt_builder_by_prompt_format(prompt_format)`

If there is no implementation for the selected `prompt_format` → **fail-fast** in the factory (English error message).

---

## `use_history` — when history is included
History is **not included automatically**.

To include history in the call:
- set `use_history: true`

Then `call_model` will read history from the prepared `state` field (history formatting is an internal responsibility of the application) and pass it as the `history` argument to either native chat mode or the manual builder.

---

## `inputs` + `prefixes` — how user content (`user_part`) is assembled
`call_model` is YAML-driven: `inputs` and `prefixes` define **what to read from state** and **how to wrap it**.

In YAML you define:
- `inputs`: part name → `state` attribute/method name
- `prefixes`: same part name → format string containing `{}`

Fail-fast rules:
1) `inputs` must be a non-empty dict
2) `prefixes` must be a non-empty dict
3) `inputs` keys must match `prefixes` keys exactly
4) every prefix must contain `{}`
5) `inputs[key]` must point to a `state` attribute/method; if it’s a method, it will be called.

Result:
- each part becomes: `prefix.format(text)`
- the final `user_part` is a concatenation of all parts (in the order of `inputs` keys).

### Example (context summarization)
```yaml
- id: call_model_summarize_context
  action: call_model
  prompt_key: "rejewski/context_summarizer_v1"
  inputs:
    evidence: context_blocks
    user_question: user_question_en
  prefixes:
    evidence: "### Evidence:\n{}\n\n"
    user_question: "### User:\n{}\n\n"
  next: call_model_answer
```

Meaning:
- system prompt: `prompts/rejewski/context_summarizer_v1.txt`
- `user_part`:
  - `evidence` ← `state.context_blocks` wrapped as `### Evidence:`
  - `user_question` ← `state.user_question_en` wrapped as `### User:`
- model output → `state.last_model_response`

---

## Generation parameters (overrides) and default values
`call_model` may optionally pass:
- `max_tokens`
- `temperature`
- `top_k`
- `top_p`

If a parameter is not provided in YAML, `call_model` **does not override** it.

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
- native chat mode: `rendered_chat_messages` (messages payload)

For convenient viewing in VS Code, use:
- https://github.com/RusieckiRoland/rag-debug-toolkit.git

---

## Working with `PrefixRouterAction` (routing by response prefix)
`call_model` is often used together with `PrefixRouterAction`.

A typical pattern:
1) `call_model` invokes the model and stores the output in `state.last_model_response`.
2) `PrefixRouterAction` inspects the beginning of the response (a prefix) and selects the next pipeline step accordingly.

Examples:
- A router LLM returns: `[DIRECT:]` / `[BM25:] {...}` / `[SEMANTIC:] {...}` → `PrefixRouterAction` routes into the proper retrieval mode or into the direct answer path.
- The model returns: `[Answer:] ...` or `[Requesting data on:] ...` → `PrefixRouterAction` decides whether to finish (`finalize`) or to perform another loop (follow-up / loop guard).

This pattern lets you use `call_model` either as a “decision” step (router) or as a “final” step (answer), depending on the selected prompt (`prompt_key`) and the prefixes configured in `PrefixRouterAction`.
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
