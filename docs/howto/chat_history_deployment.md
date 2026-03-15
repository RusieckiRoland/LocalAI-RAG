# Chat History Deployment
Wiki: [Home](../../wiki/Home.md)


This document describes how to deploy the SQL-backed chat history subsystem (tenant + soft-delete + tagging).

## Scope
This covers the durable user history storage only. Session-scoped history (Redis/in-memory) remains unchanged.

## Database setup
Choose one database engine and apply the matching combined DDL document:
- PostgreSQL: `docs/sqldb/history_security_schema_postgres.sql`
- MySQL: `docs/sqldb/history_security_schema_mysql.sql`
- MS SQL: `docs/sqldb/history_security_schema_mssql.sql`

DDL layout by engine:
- PostgreSQL: one database, two schemas: `history` and `security`
- MS SQL: one database, two schemas: `history` and `security`
- MySQL: two databases in one script: `localai_rag_history` and `localai_rag_security`

For a ready local PostgreSQL container (history + security), use:
- `docker-postgres-local/` (`postgres:17-alpine`)

Security schema includes `configuration_versions` (or `security_configuration_versions` for MySQL)
with validity window (`valid_from`, `valid_to`) and source mode (`json`/`sql`).
At application startup, if the SQL security schema is present but empty, the server bootstraps security data
from `security_conf/auth_policies.json` and `security_conf/claim_group_mappings.json`.

Provision backups and retention before enabling writes.

## Runtime config (`config*.json`)

Use `sql` section:

```json
"sql": {
  "enabled": true,
  "database_type": "${SQL_DATABASE_TYPE}",
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
  - if SQL config is provided -> startup must connect to DB; history uses SQL immediately.
  - if SQL security schema is absent or broken -> startup logs a warning and falls back to `security_conf/*.json`.
- `APP_PROFILE=prod`
  - SQL config is mandatory (`sql.enabled=true`, both connection URLs set),
  - startup must connect; history uses SQL immediately,
  - `mockSqlServer=true` is forbidden,
  - if SQL security schema is fully absent -> startup falls back to `security_conf/*.json`,
  - if SQL security schema exists but is partial or missing required data -> startup fails hard.

Connection URL note:
- PostgreSQL / MS SQL: `history.connection_url` and `security.connection_url` may point to the same physical database; objects are separated by schema.
- MySQL: `history.connection_url` and `security.connection_url` should point to different databases.

Environment variables commonly used with the provided local PostgreSQL container:

```dotenv
SQL_DATABASE_TYPE=postgres
CHAT_HISTORY_DB_URL=postgresql+psycopg://localai:<PASSWORD>@127.0.0.1:15432/localai_rag
SECURITY_DB_URL=postgresql+psycopg://localai:<PASSWORD>@127.0.0.1:15432/localai_rag
```

Runtime dependency note:
- the project environment should include `psycopg[binary]` (or an equivalent `psycopg` installation),
  because SQLAlchemy is configured to use the explicit `postgresql+psycopg` driver.

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
For security SQL bootstrap, keep `security_conf/auth_policies.json` and `security_conf/claim_group_mappings.json`
available to the server process.

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
