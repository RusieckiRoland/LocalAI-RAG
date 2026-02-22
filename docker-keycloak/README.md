# Local Keycloak (Docker) — Dev Setup

This is a **basic developer Keycloak setup** for local testing.
It uses **embedded dev database (KC_DB=dev-file)**, persisted under `/opt/keycloak/data` (Docker volume).

> For production you must configure a real database (e.g. Postgres) and proper reverse-proxy/TLS settings.

> **Security note (critical):** For production, use your organization’s trusted Identity Provider whenever possible. If you decide to use Keycloak in production, read and follow the official Keycloak documentation and hardening guidance — this is critical for the security of your system.

## Quick Start

```bash
cd docker-keycloak
cp .env.example .env
docker compose --env-file .env up -d
```

After startup:
- Keycloak URL: `http://127.0.0.1:18090`
- Admin console: `http://127.0.0.1:18090/admin`
- Login: from `.env` (`KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`)

Stop:

```bash
docker compose down
```

Stop + remove data volumes (also deletes local Keycloak data):

```bash
docker compose down -v
```

## What this is for

Use this to quickly stand up your own **local Identity Provider** when you don’t have access to a production IdP,
so you can verify how authentication works (especially on the frontend: OIDC login, redirect flow, tokens, JWKS, etc.).

## Connect to the App (config.json)

After creating your realm and client in Keycloak, set:

```json
"identity_provider": {
  "enabled": true,
  "issuer": "http://127.0.0.1:18090/realms/<your-realm>",
  "jwks_url": "http://127.0.0.1:18090/realms/<your-realm>/protocol/openid-connect/certs",
  "audience": "<your-client-id>",
  "algorithms": ["RS256"],
  "required_claims": ["sub", "exp", "iss", "aud"]
}
```
