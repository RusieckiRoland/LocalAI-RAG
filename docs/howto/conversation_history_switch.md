# Conversation history — switching from mock to real stores

This project supports conversation history with two scopes and two mocks:

1) **Session store** (ephemeral): Redis in production, in-memory mock in development.
2) **Durable store** (authoritative for authenticated users): SQL in production, mock in development.

Terminology used in code:
- `neutral` = canonical language representation (currently English)
- `translated` = optional UI/user language representation (currently Polish)

## Current wiring (default)
Server wiring lives in:
- `code_query_engine/query_server_dynamic.py`

At startup it builds:
- `_history_backend` (Redis or in-memory) via `APP_USE_REDIS`
- `_conversation_history_service` via `build_conversation_history_service(session_backend=_history_backend)`

The default `build_conversation_history_service(...)` uses:
- `KvSessionConversationStore` for the session store (backed by `_history_backend`)
- `InMemoryUserConversationStore` as the durable store (process-lifetime mock)

## Switching the session store (mock ↔ Redis)
The session store uses the same Redis toggle as the legacy HistoryManager:

- Mock (in-memory): `APP_USE_REDIS=0` (default)
- Redis: `APP_USE_REDIS=1`

If Redis is enabled, ensure Redis is reachable at the host/port used by `history/redis_backend.py`.

Optional session tuning:
- `APP_CONV_HIST_TTL_S` — TTL seconds for the session key (best-effort)
- `APP_CONV_HIST_MAX_TURNS` — max stored turns per session (default: 200)

## Switching the durable store (mock ↔ SQL)
The SQL store is not implemented in this repo yet.

To switch from the in-memory durable store to a real SQL store:

1) Implement `IUserConversationStore`:
   - interface: `code_query_engine/conversation_history/ports.py`
   - recommended location: `code_query_engine/conversation_history/durable_store_sql.py`

2) Inject it into the factory in `code_query_engine/query_server_dynamic.py`:
   - replace:
     - `build_conversation_history_service(session_backend=_history_backend)`
   - with:
     - `build_conversation_history_service(session_backend=_history_backend, durable_store=SqlUserConversationStore(...))`

3) Ensure authenticated requests provide `user_id` (identity_id) so the service writes to SQL.

## Production requirement
Production must replace **both** mocks:
- session store mock → real Redis
- durable store mock → real SQL

## Deployment notes (durable store)
High-level guidance is in `docs/howto/chat_history_deployment.md`.

## Pipeline integration points
These pipeline actions use the new service when present:
- `load_conversation_history` reads recent **neutral** Q/A into:
  - `state.history_qa_neutral`, `state.history_dialog`, `state.history_blocks`
- `finalize` writes the finalized turn (neutral + translated) via:
  - `runtime.conversation_history_service`
