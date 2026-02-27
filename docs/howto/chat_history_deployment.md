# Chat History Deployment

This document describes how to deploy the SQL-backed chat history subsystem (tenant + soft-delete + tagging).

## Scope
This covers the durable user history storage only. Session-scoped history (Redis/in-memory) remains unchanged.

## Database setup
Choose one database engine and apply the matching schema:
- PostgreSQL: `docs/sqldb/chat_history_schema_postgres.sql`
- MySQL: `docs/sqldb/chat_history_schema_mysql.sql`
- MS SQL: `docs/sqldb/chat_history_schema_mssql.sql`

If you also want SQL-backed authorization policy mappings (claim->group and group policies)
in the same database/container, apply matching security schema as well:
- PostgreSQL: `docs/sqldb/security_schema_postgres.sql`
- MySQL: `docs/sqldb/security_schema_mysql.sql`
- MS SQL: `docs/sqldb/security_schema_mssql.sql`

For a ready local PostgreSQL container (history + security), use:
- `docker-postgres-local/` (`postgres:17-alpine`)

Security schema includes `configuration_versions` (or `security_configuration_versions` for MySQL)
with validity window (`valid_from`, `valid_to`) and source mode (`json`/`sql`).
Initial seed row is `json`, so existing JSON policy files remain the source of truth by default.

Provision backups and retention before enabling writes.

## Runtime config (`config*.json`)

Use `sql` section:

```json
"sql": {
  "enabled": true,
  "database_type": "postgres",
  "connect_timeout_seconds": 5,
  "history": {
    "connection_url": "${CHAT_HISTORY_DB_URL}"
  },
  "security": {
    "connection_url": "${SECURITY_DB_URL}"
  }
}
```

Rules:
- `APP_PROFILE=dev|test`
  - if `sql.enabled=false` (or SQL URLs empty) -> app may run with mock history mode.
  - if SQL config is provided -> startup must connect to DB; connection failure is a hard startup error.
- `APP_PROFILE=prod`
  - SQL config is mandatory (`sql.enabled=true`, both connection URLs set),
  - startup must connect; failure is a hard startup error.

MySQL note:
- MySQL has no schemas in the PostgreSQL/MSSQL sense.
- You can point `history.connection_url` and `security.connection_url` to different MySQL databases.

## Current schema capabilities (MVP)

The current SQL schema provides:
- `chat_sessions` and `chat_messages` tables
- `deleted_at` for **soft delete**
- `meta_json` for extra attributes not modeled as columns

Not implemented as first‑class columns:
- `important` / `is_important` (store only in `meta_json` if needed)

If a feature is not in the schema, it is **not supported** at the DB contract level.

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
