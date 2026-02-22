# PipelineState — field purpose and meaning

This document explains what `PipelineState` is and how to interpret its fields.

## What `PipelineState` is for

`PipelineState` is the per‑run execution state for a single pipeline invocation (one user query).
It transports data between steps, allows actions to exchange information, and stores the final output.

Key properties:
- **Per‑run** (created for every query),
- Stores **inputs**, **intermediate artifacts**, **outputs**, and **diagnostics**,
- Not a cross‑run cache.

## Field groups

### 1) Request identity
- `user_query` — raw user question (original input).
- `session_id` — chat session identifier.
- `consultant` — pipeline/consultant name.
- `request_id` — optional request ID (API level).
- `branch` — optional repository branch name.
- `translate_chat` — whether translation is enabled for this run.

### 2) User and repository identity
- `user_id` — optional user identifier.
- `repository` — repository name (retrieval scope).
- `snapshot_id` — primary snapshot.
- `snapshot_id_b` — secondary snapshot (comparisons).
- `snapshot_set_id` — snapshot set (tenancy/validation).
- `snapshot_friendly_names` — mapping of snapshot IDs to display names.
- `allowed_commands` — list of UI commands allowed for this run.

### 3) Router / decision / retrieval intent
- `router_raw` — raw router payload (if preserved).
- `retrieval_mode` — retrieval mode (e.g., `semantic`, `bm25`, `hybrid`).
- `retrieval_scope` — additional retrieval scope (if used).
- `retrieval_query` — effective query for retrieval.
- `retrieval_filters` — security/scoping filters (ACL/labels/etc.).
- `query_type` — answer category (e.g., direct vs retrieval).

### 4) Retrieval history (within a run)
- `retrieval_queries_asked` — queries already executed in this run.
- `retrieval_queries_asked_norm` — normalized form used to prevent repeats.

### 5) Last search (diagnostics / prompt hygiene)
- `last_search_query` — last search query used.
- `last_search_type` — last search type (`bm25`/`semantic`/`hybrid`).
- `last_search_filters` — filters used for the last search.
- `last_search_bm25_operator` — `and`/`or` operator for BM25, if applicable.
- `sufficiency_search_mode_constraint` — constraint used by sufficiency logic.

### 6) Retrieved material
- `node_texts` — list of retrieved node texts/chunks.

### 7) Context and history
- `history_dialog` — conversation history in dialog format.
- `history_blocks` — historical context blocks.
- `history_qa_neutral` — neutralized Q/A history.
- `context_blocks` — current context blocks for prompt assembly.

### 8) Model outputs
- `last_model_response` — last raw model response.
- `banner_neutral` — banner for the neutral answer.
- `banner_translated` — banner for the translated answer.
- `llm_server_security_override_notice` — security override notice (if any).

### 9) Answer fields
- `answer_neutral` — answer in neutral language.
- `answer_translated` — translated answer.
- `classification_labels_union` — union of classification labels seen.
- `acl_labels_union` — union of ACL labels seen.
- `doc_level_max` — max document level observed.
- `final_answer` — final answer used by the engine.

### 10) Translation artifacts
- `user_question_neutral` — normalized user question.
- `user_question_translated` — translated user question.

### 11) Diagnostics
- `step_trace` — executed step trace.
- `steps_used` — number of executed steps.

### 12) Graph / dependency expansion
- `retrieval_seed_nodes` — retrieval seed nodes.
- `graph_seed_nodes` — graph seed nodes.
- `graph_expanded_nodes` — expanded graph nodes.
- `graph_edges` — graph edges.
- `graph_debug` — graph debug data.
- `turn_loop_counter` — per‑run loop counter.
- `loop_counters` — per‑step loop counters.

### 13) Model input (logging)
- `model_input_en` — model input text (logging/diagnostics).

### 14) Inbox (runtime messaging)
- `inbox` — per‑run message queue.
- `inbox_last_consumed` — last consumed messages (for logging).

## Notes
- `PipelineState` is a runtime contract. Changes should be made cautiously.
- Removing fields requires checking actions, tests, and documentation.
