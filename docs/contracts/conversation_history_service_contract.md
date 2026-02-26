# Conversation History Service — Contract (EN)

## Goal
Provide a professional, scalable way to persist and replay conversation history with two scopes:

1) **Session-scoped history (ephemeral)** — always available via `session_id` and stored in Redis (or in-memory mock).
2) **User-scoped history (durable)** — available for authenticated users via `identity_id` and stored in a SQL database.

The system must preserve language pairing and identity mapping:
- `session_id` is always present.
- Conceptual model (do not bind to concrete languages):
  - `question_neutral` / `answer_neutral` (required)
  - `question_translated` / `answer_translated` (optional)

Current project mapping (today):
- neutral = English (`question_neutral` / `answer_neutral`)
- translated = Polish (`question_translated` / `answer_translated`)
- For authenticated users:
  - `identity_id` must be linked with `session_id`.

## Non-goals (for now)
- User-facing UI/API to browse history from SQL.
- Semantic search over history (can be added later).
- Storing retrieval chunks, routing outputs, intermediate steps, or prompts in conversation history.

## Data model

### Turn (canonical record)
Each user request produces exactly one **turn**:
- `turn_id` (UUID)
- `session_id` (string, required)
- `identity_id` (string, optional; from Identity Provider)
- `request_id` (string, required; idempotency key per HTTP request)
- `created_at`, `finalized_at`
- `pipeline_name`, `consultant`, `repository` (optional metadata)
- `translate_chat` (bool)
- `question_neutral` (string, required)
- `answer_neutral` (string, required once finalized)
- `question_translated` (string, optional)
- `answer_translated` (string, optional)
- `answer_translated_is_fallback` (bool, optional; true if `answer_translated` was not translated but copied from neutral)
- `metadata` (object; recommended to persist as JSONB in SQL)
- `record_version` (int, optional)
- `replaced_by_turn_id` (UUID, optional)
- `deleted_at` (timestamp, optional; soft-delete / redaction marker)

**Invariants**
- `session_id` is required for all turns.
- `request_id` must be unique per session:
  - unique by `(session_id, request_id)` in the session store
  - for authenticated storage, unique by `(identity_id, session_id, request_id)`
- `question_neutral` must always be stored (English-neutral).
- `answer_neutral` must always be stored for finalized turns.
- For authenticated users: `identity_id` is stored and linked to `session_id`.
- If translation is not performed, `question_translated` / `answer_translated` may be empty.
- If `translate_chat=true`, `answer_translated` should be present; if not, the system should set `answer_translated_is_fallback=true` when falling back.

**Neutral (EN) generation rules**
- `question_neutral` must be produced at request start.
- If EN translation is unavailable or fails:
  - store the original question text in `question_neutral` (fallback copy), and
  - record the fallback in `metadata` (e.g. `question_neutral_is_fallback=true`).

**request_id vs turn_id (idempotent start)**
- `request_id` is the idempotency key; `turn_id` is the canonical identifier of the stored turn.
- `start_turn` must be idempotent:
  - for the same `(session_id, request_id)` it MUST return the same `turn_id` (not raise on duplicates).

## Storage architecture

### A) Session store (Redis / mock) — fast + ephemeral
Purpose:
- provide “recent Q/A context” for prompt history injection
- survive within a session window

Characteristics:
- keyed by `session_id`
- TTL-based retention (configurable)
- optimized for append / fetch last N turns
- must enforce a hard cap on stored turns per session (anti-spam / bounded memory)

**TTL recommendation**
- TTL must be configurable and **longer than the longest expected user session**.
- Typical production values range from **30 minutes to 7 days** depending on UX.
- A reasonable default is **24 hours**, plus a hard cap on stored turns.

**Anti-spam / size controls (recommended)**
- Maintain only the last **N turns** per session (e.g. `N=200..500`) and drop the oldest on append.
- Hard cap is enforced on every append; TTL expires the whole session key later.
- Optionally enforce rate limits per `session_id` / `identity_id` at the server layer.

### B) Durable store (SQL) — authoritative for authenticated users
Purpose:
- long-term persistence and reconstruction
- auditing, compliance, future reporting

Characteristics:
- keyed by `identity_id` with index on `session_id` and time
- stores canonical “Turn” records (`neutral` always; `translated` optional)
- persist `metadata` as JSONB for forward-compatible auditing (IP hash, user-agent, channel, etc.)

**Metadata safety (recommended)**
- Do not store raw PII in `metadata` (e.g. raw IP). Prefer stable hashes (e.g. `ip_hash`) and allowlisted keys.
- Do not store full prompts, retrieved chunks, or internal trace payloads in history metadata.

### C) ConversationHistoryService — orchestrator
A single server-side component responsible for writing to:
- Redis for every request (session scope)
- SQL additionally when `identity_id` is present

This component is also responsible for linking:
- `session_id` ⇔ `identity_id`

## Contracts (ports / interfaces)

### 1) Session conversation store (ephemeral)
`ISessionConversationStore`
- `start_turn(*, session_id: str, request_id: str, identity_id: str | None, question_neutral: str, question_translated: str | None, translate_chat: bool, meta: dict | None) -> str turn_id`
- `finalize_turn(*, session_id: str, request_id: str, turn_id: str, answer_neutral: str, answer_translated: str | None, answer_translated_is_fallback: bool | None, meta: dict | None) -> None`
- `list_recent_finalized_turns(*, session_id: str, limit: int) -> list[ConversationTurn]`

Implementation examples:
- Redis list/stream per session (recommended) rather than rewriting one large JSON blob.
- `finalize_turn` must be idempotent: repeated calls for the same `(session_id, turn_id)` must not corrupt data.

**Finalize without start**
- **Production:** missing `turn_id` on finalize is a **hard error** (fail-fast).
- **Dev/Test only:** a best‑effort fallback may be enabled:
  - if `turn_id` is missing on finalize, call `start_turn(...)`, then finalize.
- Store implementations should still treat explicit `(session_id, turn_id)` mismatches as errors.

### 2) User conversation store (durable)
`IUserConversationStore`
- `upsert_session_link(*, identity_id: str, session_id: str) -> None`
- `insert_turn(*, turn: Turn) -> None`
- `upsert_turn_final(*, identity_id: str, session_id: str, turn_id: str, answer_neutral: str, answer_translated: str | None, answer_translated_is_fallback: bool | None, finalized_at_utc: str | None, meta: dict | None) -> None`

Notes:
- Writes should be idempotent by natural keys (e.g. `(identity_id, session_id, turn_id)`).
- Prefer upsert semantics for finalization to handle retries/races safely.
- `finalized_at_utc` should be treated as UTC and preferably set server-side by the storage layer (authoritative timestamps).
- A finalized turn is expected to already exist (created by `insert_turn`); `upsert_turn_final` updates final fields.

### 3) ConversationHistoryService (server-level)
`IConversationHistoryService`
- `on_request_started(...) -> turn_id`
  - called once per HTTP request before pipeline execution
  - ensures `question_neutral` is written
  - ensures `session_id ⇔ identity_id` link for authenticated users
- `on_request_finalized(...) -> None`
  - called from `finalize` when `final_answer` is determined
  - writes `answer_neutral` + optional `answer_translated`

**Metadata forwarding (recommended)**
- `IConversationHistoryService` should forward an allowlisted subset of `meta` into SQL `metadata` (e.g. `channel`, `device_type`, `ip_hash`).
- Non-allowlisted keys should be treated as ephemeral and not persisted in SQL by default.

## Session merge strategy (unauthenticated → authenticated)
The system must handle the common flow:
unauthenticated user starts a conversation → user logs in → continues in the same browser session.

Recommended behavior:
- Keep the same `session_id` and begin attaching `identity_id` once available.
- On the first authenticated request for a `session_id` that previously had no identity:
  - call `upsert_session_link(identity_id, session_id)`
  - optionally (best-effort) backfill/migrate the last N session turns from Redis into SQL as user turns
    (idempotent inserts keyed by `(identity_id, session_id, turn_id)`).
  - Backfill should preserve chronology (use `created_at` or the order stored in Redis).

**Conflict rule (required)**
- If a `session_id` is already linked to an `identity_id`, linking it to a *different* `identity_id` must be rejected and logged
  (security/audit).

Orphan sessions:
- Session-only conversations without `identity_id` are expected and should expire via Redis TTL.

## Pipeline integration points

### Where history is written
1) **Request start (server layer)**:
   - Create a new turn and write `question_neutral` (and `question_translated` if present).
   - Store `turn_id` on pipeline state so `finalize` can update the same turn.

2) **Finalize action**:
   - Calls history service with `answer_neutral` and `answer_translated` (if present).

### Where history is read
`load_conversation_history` should load **English Q/A pairs** (neutral language) into the pipeline state:
- `Dict(question_neutral, answer_neutral)` or a list of such dicts.
- The prompt composition layer decides how to render it.

## Record updates / redaction
- `record_version` / `replaced_by_turn_id` enable corrections without losing auditability.
- `deleted_at` marks a turn as redacted/soft-deleted:
  - it should not be returned by prompt-history reads,
  - user-visible history reads (future) should exclude redacted turns by default.
  - the session store should also respect redaction (remove or tombstone the turn so it is not re-injected into prompts until TTL).

**Redaction policy (recommended)**
- Prefer a tombstone-style redaction:
  - keep identifiers and timestamps,
  - clear textual content fields (`question_*`, `answer_*`) or replace them with a fixed placeholder,
  - retain `deleted_at` as the authoritative marker.

## Weaviate recommendation (history storage)

### Can Weaviate be used as the primary history database?
Not recommended.
- Conversation history is transactional/audit data: correctness, ordering, retention, user filtering, and compliance are best served by SQL.
- “Export later to SQL” turns Weaviate into the source of truth and adds complexity (backfill, reconciliation, idempotency, data-loss risk).

### Where Weaviate fits well
Recommended as an **optional secondary index**:
- semantic recall/search over past turns
- similarity lookup (“have we answered this before?”)

Preferred data flow:
- **SQL is the source of truth**
- asynchronous replication/indexing into Weaviate for fast semantic retrieval
- Weaviate data is rebuildable from SQL

## Future extensibility
This contract supports later additions without breaking writes:
- conversation browser APIs (SQL reads)
- user/session replay
- semantic history retrieval (Weaviate index)
- analytics and retention policies
- conversation summarization (e.g. `summary_neutral`, `summary_translated`) to reduce token consumption in long sessions
