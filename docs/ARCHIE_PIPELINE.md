# RAG-for-Code Pipeline Design (FAISS + Graph + Router + History + Inheritance)

This document defines a **clear, implementable** pipeline for answering developer questions against a real codebase (e.g., .NET + SQL), using:

- **FAISS semantic retrieval** (vector search),
- **BM25 keyword retrieval** (inverted index),
- **SemanticRerank** (FAISS widen + lightweight keyword rerank) *(implemented)*,
- **HybridSearch** = Semantic + BM25 + **RRF** *(planned; not implemented yet)*,
- a **dependency graph** produced by *RoslynIndexer* (nodes + edges),
- a **router/planner** model call that selects retrieval mode,
- **conversation history** load + summarization,
- **token budgeting** + summarization when limits are exceeded,
- **YAML pipeline inheritance** to avoid copy-paste.

Core idea: **retrieval finds entry points; the graph explains structure; targeted lookups fetch exact bodies/snippets; summarizers keep everything within budgets.**

---

## 0. Terms and Data Model

### 0.1 User inputs (per request)
- `UserQuestion` – raw question.
- `IsEnglish` – boolean:
  - `True`  → user asked in English,
  - `False` → user asked in another language (e.g., Polish).

### 0.2 Pipeline settings (per pipeline / per repository)
Minimum required settings:

- `repository` – repository/project name, e.g. `"nopCommerce"`.
- `active_index` – which built index to use, e.g. `"2025-12-14_develop"`.
- `model_language` – model language for prompts (typically `"en"`).
- `entry_step_id` – **deterministic start step** for the pipeline (see §10).

Token budgets:

- `max_context_tokens` – max tokens for the **evidence context** injected into the ANSWER call
  (retrieval hits + graph neighborhood + targeted node texts).
- `max_history_tokens` – max tokens reserved for **conversation history** injected into router/answer prompts.

Loop guard:

- `max_turn_loops` – hard cap for follow-up iterations per user turn (typical: 3–5).

Graph expansion defaults:

- `graph_max_depth` – traversal depth (bounded).
- `graph_max_nodes` – maximum nodes collected (bounded).
- `graph_edge_allowlist` – allowed edge types for traversal.

Targeted fetch limits:

- `node_text_fetch_top_n` – how many node bodies/snippets can be fetched by identity after graph expansion.

Retrieval mode availability:

- `retrieval_modes` – list of modes the server supports (a capability list).
  Example: `["semantic","bm25","hybrid","semantic_rerank"]`.

History policy:

- `history_summarization_policy` – recommended: `"incremental_resummarize"` (see §2.2).

---

## 1. Phase A — Question Normalization (Translate In)

**Goal:** downstream prompts operate on a stable English question, without backend language detection.

- If `IsEnglish == True` → `UserQuestionEN = UserQuestion`.
- If `IsEnglish == False` → translate `UserQuestion` to English → `UserQuestionEN`.
- Keep original user language to translate final output back if needed.

**Outputs:**
- `UserQuestionEN`
- `UserQuestionOriginal` (raw)

---

## 2. Phase B — Conversation History (Load + Summarize)

### 2.1 Load history
Load past conversation turns for this user/session:
- user question + assistant answer, in chronological order.

**Output:** `HistoryRaw` (list of turns)

### 2.2 Summarize history if needed (query-aware, incremental)
If `HistoryRaw` exceeds `max_history_tokens` (after formatting for prompt injection):

- produce a `HistorySummary` that fits `max_history_tokens`,
- summary must be **conditioned on `UserQuestionEN`** (keep what matters for this question).

#### Rolling summary rule (must)
Once history exceeds the limit and is summarized the first time:

1. Persist `HistorySummary` (and a pointer/version).
2. In subsequent turns:
   - inject `HistorySummary` + **only the newest raw turns since the summary**.
3. If the injected history exceeds the budget again:
   - **re-summarize** `HistorySummary + NewTurns` into a new `HistorySummary`.
   - persist the updated summary and advance the pointer.

This guarantees history stays bounded and avoids repeatedly summarizing the entire raw log.

**Outputs:**
- `HistoryForPrompt` – either:
  - `HistorySummary (+ new raw turns)` or
  - `HistoryRaw` if it fits.

---

## 3. Phase C — Router / Planner (Model Call)

**Goal:** decide whether to skip retrieval (DIRECT) or do retrieval, and if retrieval: **which mode** and what query to run.

### 3.1 Router output protocol (must)
Router returns **exactly one line** with exactly one prefix:

- `[SEMANTIC:] <better semantic query>`
- `[SEMANTIC_RERANK:] <better query (optionally with keyword hints)>`
- `[BM25:] <keywords or keyword-style query>`
- `[HYBRID:] <better hybrid query>`
- `[DIRECT:] <empty or direct question>`

### 3.2 Meaning of modes
- `DIRECT` → answer from general knowledge (skip repo retrieval).
- `SEMANTIC` → FAISS semantic retrieval (implemented).
- `SEMANTIC_RERANK` → FAISS widen + keyword rerank (implemented).
- `BM25` → keyword retrieval via BM25 artifacts (supported when artifacts exist).
- `HYBRID` → **HybridSearch** = Semantic + BM25 + RRF (planned, not implemented yet).

**Output:**
- `RetrievalPlan` = `{ mode, query_or_keywords }`

---

## 4. Phase D — Execute Retrieval (Fetch More Context)

**Goal:** retrieve candidate evidence and produce graph entry points.

### 4.1 SEMANTIC (implemented)
- Run FAISS vector search using router query.
- Return top-N chunks (with stable identifiers).

### 4.2 SEMANTIC_RERANK (implemented)
This is **not HybridSearch**. It is semantic retrieval with local reranking:

1. Run FAISS with a widened pool (example policy):
   - `widen = max(50, top_k * 3)` (exact formula is an implementation detail).
2. Compute keyword score on candidates (no extra index).
3. Blend scores (example):
   - `final = alpha * semantic_score + beta * keyword_score_norm`
4. Sort by `final`, trim to `top_k`.

### 4.3 BM25 (supported when artifacts exist)
- Run BM25 retrieval against the repository index.

**If BM25 artifacts are missing**:
- either fail fast with a clear error, **or**
- fall back to `SEMANTIC` (policy decision; must be deterministic and logged).

### 4.4 HYBRID (planned; not implemented yet)
**HybridSearch = Semantic + BM25 fused by RRF (Reciprocal Rank Fusion)**

1. Run Semantic (FAISS) → ranked list `S`.
2. Run BM25 → ranked list `B`.
3. Fuse with RRF:
   - each doc gets a combined score based on rank positions in `S` and `B`.
4. Return fused top-N.

**Output (all modes):**
- `RetrievedChunks` – list of retrieved evidence items.
- `EntryCandidates` – normalized identifiers extracted from hits (chunk ids, node keys, file paths, etc.).

---

## 5. Phase E — Graph Expansion (When to “Pull the Dependency Tree”)

**Answer:** **immediately after retrieval**, before assembling the final context for the answer model.

### 5.1 Convert retrieval hits → graph entry nodes
Map `EntryCandidates` to graph node keys (examples):
- `dbo.Invoice|TABLE`
- `dbo.Invoice_Create|PROC`
- `csharp:MyApp.InvoiceService|TYPE`
- `csharp:MyApp.InvoiceController.SomeAction|METHOD`

**Output:** `EntryNodes`

### 5.2 Walk the graph (bounded)
Run bounded traversal around `EntryNodes`:

- depth ≤ `graph_max_depth`
- nodes ≤ `graph_max_nodes`
- edges restricted to `graph_edge_allowlist`

**Output:** `GraphNeighborhood` (subgraph relevant to the question)

### 5.3 Targeted text fetch (recommended)
Fetch concrete bodies/snippets for the most relevant nodes:

- stored procedure bodies
- method bodies
- migration summaries
- key DDL fragments (or summaries)

This is a **lookup by identity** (node key → body/snippet), not global searching again.

**Output:** `NodeTexts`

---

## 6. Phase F — Context Assembly + Token Budgeting

### 6.1 Compose the evidence context (ContextPack)
Typical inputs to the ANSWER model call:

- `UserQuestionEN`
- `HistoryForPrompt` (summary + recent turns)
- `RetrievedChunks`
- `GraphNeighborhood` (structured + compact)
- `NodeTexts` (targeted snippets/bodies)

**Note:** keep identifiers stable (node keys, file paths, object names).

### 6.2 Check context budget for evidence
If evidence context exceeds `max_context_tokens`:

- summarize `RetrievedChunks + GraphNeighborhood + NodeTexts`
- summary must be **query-aware** (conditioned on `UserQuestionEN`)
- preserve stable identifiers (do not lose node keys)

This summarization is itself a **model call** with a dedicated prompt.

**Output:**
- `ComposedContextForAnswer` (raw or summarized)

---

## 7. Phase G — Specialist Answer (Model Call) + Follow-up Loop

### 7.1 Answer output protocol (must)
Answer call returns one of:

- `[Answer:] ...` – final answer in English
- `[Requesting data on:] ...` – a follow-up request to retrieve more evidence

### 7.2 Looping rule (must)
If output starts with `[Requesting data on:]`:

1. increment `turn_loop_counter`
2. if `turn_loop_counter > max_turn_loops`:
   - stop looping and finalize with a safe explanation (no hallucinations)
3. else:
   - run retrieval again (Phase D)
   - expand graph again (Phase E)
   - re-check budgets (Phase F)
   - call answer again (Phase G)

**Output:**
- `FinalAnswerEN` or a safe finalization

---

## 8. Phase H — Translate Out + Persist Turn

### 8.1 Translate out
If `IsEnglish == False`, translate `FinalAnswerEN` back to user language.

### 8.2 Persist history
Persist the completed turn:
- user question (raw + EN version)
- assistant answer (EN + translated if needed)

Persist summary state:
- if `HistorySummary` exists, keep pointer/version and "new turns since summary" counters.

---

## 9. Retrieval Modes Summary (Current vs Planned)

Implemented:
- **SEMANTIC** → FAISS only
- **SEMANTIC_RERANK** → FAISS widen + keyword rerank

Supported (when artifacts exist):
- **BM25** → BM25 inverted index retrieval

Planned (not implemented yet):
- **HYBRID** → **HybridSearch** = Semantic + BM25 + RRF

No retrieval:
- **DIRECT** → general knowledge answer

---

## 10. YAML Execution Model (Deterministic Pipeline)

### 10.1 Step graph (recommended contract)
Each step is a node in a directed execution graph:

- `id` (unique)
- `action`
- deterministic transition:
  - either `next: <step_id>` **or**
  - conditional transitions (e.g. `on_ok`, `on_over_limit`, `on_semantic`, ...)

**Rule:**
- every step must deterministically choose the next step based on its outputs,
- only the entry selection is defined globally via `settings.entry_step_id`.

### 10.2 Required generic actions (by responsibility)
- `translate_in_if_needed`
- `load_conversation_history`
- `check_context_budget` (budget gate)
- `call_model` (router, summarizers, answer)
- `handle_prefix` (router prefixes, answer/follow-up prefixes)
- `fetch_more_context` (per retrieval mode)
- `expand_dependency_tree` (graph traversal)
- `fetch_node_texts` (targeted lookup by identity)
- `loop_guard` (enforce `max_turn_loops`)
- `persist_turn_and_finalize`
- `finalize` (translate out + UI formatting)

---

## 11. YAML Inheritance (“extends”) — Exact Rules

Inheritance is used to avoid duplicating a pipeline when only a few settings change (e.g., different repository/index).

### 11.1 Syntax
```yaml
pipeline:
  name: rejewski_code_analysis_nopCommerce_develop
  extends: rejewski_code_analysis_base
  settings:
    repository: "nopCommerce"
    active_index: "2025-12-14_develop"
```

### 11.2 Merge algorithm (must, simple and deterministic)

Given a `child` pipeline and a `parent` pipeline (resolved from `extends`):

#### A) `settings` merge
- perform a **deep merge** (dictionary merge):
  - if a key exists only in parent → keep parent value
  - if a key exists in child → child **overrides** parent
  - nested dictionaries are merged recursively

#### B) `steps` merge (your rule)
Steps are merged **by `id`**:

- If child defines a step with a **new `id`** → it is **added**.
- If child defines a step with an `id` that already exists in parent → it **overrides** the parent step (replacement).

**Ordering:**
- YAML list order is only for readability, not execution.
- Execution is determined by `next`/branches, starting at `entry_step_id`.

#### C) `entry_step_id`
- execution starts from `settings.entry_step_id` after inheritance merge.

### 11.3 Multiple inheritance levels
- A pipeline may extend another pipeline that itself extends a base pipeline.
- Resolution order must be deterministic: resolve from root parent → … → child, applying merges in sequence.

### 11.4 Validation (must)
After merge:
- `entry_step_id` must exist and point to a defined step
- every referenced `next`/branch step id must exist
- (recommended) detect unreachable steps and report warnings/errors

---

## 12. Practical rules (“don’t search forever”)

1. Use retrieval to find **entry points**.
2. Pull the dependency tree via the graph **right after retrieval**.
3. Use targeted lookups to fetch missing bodies/snippets.
4. If entry points remain weak after 1–2 attempts, stop and be explicit (no hallucinations).
5. Always enforce `max_turn_loops`.

---

## 13. Implementation checklist (what must exist in code)

To implement this spec cleanly, the runtime needs:

- Pipeline loader:
  - parse YAML
  - resolve `extends`
  - merge settings + steps (rules above)
  - validate determinism (entry step, transitions)

- Execution engine:
  - pipeline state storage (question, history, plan, context, counters)
  - step dispatcher (action → function)
  - transition resolver (next/branch)
  - loop counter + guard

- History store:
  - append turns
  - fetch turns by session/user id
  - store and reuse `HistorySummary` + pointer/version
  - incremental re-summarize when needed

- Retrieval providers:
  - FAISS semantic
  - BM25 keyword
  - SemanticRerank (implemented)
  - HybridSearch (planned)

- Graph provider:
  - load RoslynIndexer artifacts
  - expand bounded neighborhood
  - map chunk hits to node keys
  - targeted body/snippet lookup by identity

- Summarizers:
  - history summarizer prompt (query-aware)
  - evidence/context summarizer prompt (query-aware, identifier-preserving)

---

## Appendix A — Reference prefixes

Router prefixes:
- `[SEMANTIC:]`
- `[SEMANTIC_RERANK:]`
- `[BM25:]`
- `[HYBRID:]`
- `[DIRECT:]`

Answer prefixes:
- `[Answer:]`
- `[Requesting data on:]`

These must be parsed strictly and treated as protocol markers, not user-visible content.
