# HistoryManager – Design & Implementation Plan

## 1. Problem Statement

The conversation history was previously polluted by:
- context fragments returned by retrievers (BM25 / semantic),
- intermediate model outputs (router decisions, follow-up queries),
- multiple internal iterations within a single turn.

This caused:
- rapid exhaustion of the model context window,
- loss of conversational clarity for the model,
- lack of control over what is actually injected into prompts as “history”.

The goal is to **radically slim down conversation history** while preserving its semantic continuity.

---

## 2. Core Principle

**HistoryManager stores only:**
- the original user question,
- the final model answer returned to the user.

Everything else (retrieval results, routing outputs, diagnostics, intermediate prompts) is **not conversation history** and must never be persisted in HistoryManager.

---

## 3. Data Model (Conversation Turn)

Each conversation turn consists of:

```
Turn:
- user_query: string
- final_answer: string
- timestamp
```

Optional (future-proofing):
```
- user_query_en
- final_answer_en
```

Explicitly NOT stored:
- system/user/assistant role messages,
- code chunks,
- retriever outputs,
- follow-up queries,
- pipeline metadata.

---

## 4. Session and User Identification

### 4.1 Session ID (current)
- Each conversation is identified by a `session_id`.
- `session_id` is generated on the first request and passed with subsequent requests.
- HistoryManager operates strictly per `session_id`.

### 4.2 User ID (future support)
- HistoryManager also stores `user_id` (currently `None`).
- It does not affect logic yet.
- It enables future features:
  - authenticated users,
  - mapping multiple sessions to a single user,
  - replaying a user’s historical sessions.

---

## 5. History Storage Backend

### 5.1 Backend Contract (IHistoryBackend)

HistoryManager depends only on an abstract backend contract, e.g.:

```
- start_turn(session_id, user_id, user_query)
- finalize_turn(session_id, final_answer)
- get_history(session_id, limit)
- clear_session(session_id)
```

### 5.2 Backend Implementations

#### a) InMemory / HistoryMock (dev & test)
- Simple in-process dictionary.
- Data is lost on server restart.
- Zero external dependencies.
- Used for development and automated tests.

#### b) Redis Backend (target)
- History stored in Redis per `session_id`.
- Session-level TTL (e.g. several days).
- Stateless backend enables horizontal scaling.
- Production-ready design.

HistoryManager remains unaware of which backend is used.

---

## 6. Lifecycle of a Conversation Turn

### 6.1 Turn Start
When a user request arrives:

```
HistoryManager.start_user_query(session_id, user_id, user_query)
```

A pending turn is created.

### 6.2 Pipeline Execution
The pipeline performs:
- routing,
- retrieval,
- iterative loops,
- heuristics,
- translations.

None of this data is written to history.

### 6.3 Turn Finalization
Once the final answer is produced:

```
HistoryManager.set_final_answer(session_id, final_answer)
```

The turn becomes complete and durable.

---

## 7. Using History in Prompts

HistoryManager exposes history exclusively as compact Q/A pairs, e.g.:

```
### Conversation history:
User: How does the pipeline work?
Assistant: The pipeline routes the query and retrieves relevant context.

User: How is history handled?
Assistant: Only final Q/A pairs are stored to keep the context small.
```

No code, no documents, no retriever output.

History provides **dialog continuity**, not knowledge.

---

## 8. Logging vs History

- Full prompts, retrieved context, intermediate model outputs are written to logs
  (via InteractionLogger).
- HistoryManager is **not** a debugging or tracing tool.
- Clear separation of responsibilities:
  - History → conversational semantics.
  - Logs → diagnostics and observability.

---

## 9. Final Outcome

With this design:
- conversation history remains short and predictable,
- context limits are not exhausted after a few turns,
- the model receives a clean conversational signal,
- the system is ready for:
  - Redis-backed storage,
  - horizontal scaling,
  - authenticated users and session replay.

---

## 10. Status

- [x] Design finalized
- [x] HistoryManager reduced to Q/A-only persistence
- [x] E2E tests aligned with new history semantics
- [ ] Redis backend implementation
- [ ] User authentication and session replay
