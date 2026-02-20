# Chat History Deployment

This document describes how to deploy the SQL-backed chat history subsystem (tenant + soft-delete + tagging).

## Scope
This covers the durable user history storage only. Session-scoped history (Redis/in-memory) remains unchanged.

## Database setup
Choose one database engine and apply the matching schema:
- PostgreSQL: `docs/chat_history_schema_postgres.sql`
- MySQL: `docs/chat_history_schema_mysql.sql`
- MS SQL: `docs/chat_history_schema_mssql.sql`

Provision backups and retention before enabling writes.

## Backend configuration
Expose a dedicated connection string for chat history, for example `CHAT_HISTORY_DB_URL`.
Run migrations/DDL during deploy and verify connectivity at startup.

## API layer
Expose the dedicated history endpoints under `/chat-history`:
- `GET /chat-history/sessions?limit=50&cursor=...&q=...`
- `GET /chat-history/sessions/{sessionId}`
- `GET /chat-history/sessions/{sessionId}/messages?limit=100&before=...`
- `POST /chat-history/sessions`
- `POST /chat-history/sessions/{sessionId}/messages`
- `PATCH /chat-history/sessions/{sessionId}`
- `DELETE /chat-history/sessions/{sessionId}`

All reads and writes must filter by `tenant_id` and `user_id`.
Soft-deleted rows are excluded by default (`deleted_at IS NULL`).

## Frontend integration
Replace localStorage history with API calls:
- Load sessions list on startup.
- Fetch messages only after a session is selected.
- Use paging for long histories.

## Rollout strategy
Start with read-only history and validate correctness.
Enable writes after read paths are verified.
Disable localStorage history once backend history is stable.

## Observability
Track request latency and error rate for history endpoints.
Capture counts for sessions/messages per user and tenant.
