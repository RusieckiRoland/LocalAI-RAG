# Local PostgreSQL (Docker) — history + security

Minimal local PostgreSQL container for:
- combined history + security DDL (`docs/sqldb/history_security_schema_postgres.sql`)

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

The application environment should include `psycopg[binary]` (the repo `environment.yml` does),
so the explicit SQLAlchemy driver `postgresql+psycopg://...` works without separate PostgreSQL client setup.

The script creates `history` and `security` schemas inside the same PostgreSQL database.
On first application startup, if `security` is empty, the server bootstraps the SQL tables
from `security_conf/auth_policies.json` and `security_conf/claim_group_mappings.json`.

## Notes

- SQL init scripts run only on first boot (empty volume).
- Root project `.env` should use the same DB name/user/password as `docker-postgres-local/.env`.
- To re-run schema init from scratch:

```bash
docker compose down -v
docker compose --env-file .env up -d
```
