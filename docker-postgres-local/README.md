# Local PostgreSQL (Docker) — history + security

Minimal local PostgreSQL container for:
- chat history schema (`docs/sqldb/chat_history_schema_postgres.sql`)
- security schema (`docs/sqldb/security_schema_postgres.sql`)

Uses the lightweight image: `postgres:17-alpine`.

## Quick start

```bash
cd docker-postgres-local
cp .env.example .env
docker compose --env-file .env up -d
```

After startup:
- Postgres host: `127.0.0.1`
- Postgres port: `15432` (configurable)
- DB/user/password from `.env`

Example env vars for app config:

```bash
CHAT_HISTORY_DB_URL=postgresql+psycopg://localai:<PASSWORD>@127.0.0.1:15432/localai_rag
SECURITY_DB_URL=postgresql+psycopg://localai:<PASSWORD>@127.0.0.1:15432/localai_rag
```

## Notes

- SQL init scripts run only on first boot (empty volume).
- To re-run schema init from scratch:

```bash
docker compose down -v
docker compose --env-file .env up -d
```
