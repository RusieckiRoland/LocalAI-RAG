# Local Keycloak (Docker)

## Quick Start

```bash
cd docker-keycloak
cp .env.example .env
docker compose up -d
```

After startup:
- Keycloak URL: `http://127.0.0.1:18090`
- Admin console: `http://127.0.0.1:18090/admin`
- Default login: from `.env` (`KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`)

Stop:

```bash
docker compose down
```

Stop + remove data volumes:

```bash
docker compose down -v
```

## Connect to the App

After creating your realm/client in Keycloak, set this in `config.json`:

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
