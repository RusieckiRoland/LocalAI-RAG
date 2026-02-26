# Keycloak OIDC (PKCE) Setup for LocalAI-RAG

This guide explains how to configure Keycloak so that:
- the browser UI can log in using **OIDC Authorization Code Flow with PKCE**, and
- the API can validate JWTs strictly, including **issuer** and **audience**.

## 1. Keycloak realm

Create (or use) a realm, for example: `localai-rag`.

Issuer URL will look like:
- `http://127.0.0.1:18090/realms/localai-rag`

## 2. Create the UI client (SPA): `localai-rag-ui`

Create a client:
- Client ID: `localai-rag-ui`
- Client type: OpenID Connect
- Client authentication: Off (public client)
- Standard flow: On
- Direct access grants: Off
- Implicit flow: Off

Redirects / origins for local UI (server serves UI on `:5000` by default):
- Valid redirect URIs:
  - `http://127.0.0.1:5000/*`
  - `http://localhost:5000/*`
- Web origins:
  - `http://127.0.0.1:5000`
  - `http://localhost:5000`

Notes:
- PKCE is used by the frontend automatically (S256).
- Keep redirect URIs as strict as possible in real environments.

## 3. Create the API audience client: `localai-rag-api`

Create a second client to represent the API as a token audience:
- Client ID: `localai-rag-api`
- Client type: OpenID Connect

This client is used for **audience mapping**. The API validates that access tokens include:
- `aud` containing `localai-rag-api`

## 4. Add Audience mapper so UI tokens include API audience

Goal: tokens obtained by `localai-rag-ui` must have `aud` including `localai-rag-api`.

In Keycloak:
1. Go to Clients -> `localai-rag-ui`
2. Add an **Audience** mapper (location depends on Keycloak version; it can be under Client scopes / Mappers):
   - Mapper type: Audience
   - Included Client Audience: `localai-rag-api`
   - Add to access token: On

After this, the access token for the UI should contain:
- `iss`: your realm issuer
- `aud`: includes `localai-rag-api`

## 5. App configuration

Set the app config (example for local Keycloak):

```json
{
  "auth": {
    "oidc": {
      "enabled": true,
      "issuer": "http://127.0.0.1:18090/realms/localai-rag",
      "resource_server": {
        "enabled": true,
        "jwks_url": "http://127.0.0.1:18090/realms/localai-rag/protocol/openid-connect/certs",
        "audience": "localai-rag-api",
        "algorithms": ["RS256"],
        "required_claims": ["sub", "exp", "iss", "aud"]
      },
      "client": {
        "client_id": "localai-rag-ui",
        "authorization_endpoint": "http://127.0.0.1:18090/realms/localai-rag/protocol/openid-connect/auth",
        "token_endpoint": "http://127.0.0.1:18090/realms/localai-rag/protocol/openid-connect/token",
        "end_session_endpoint": "http://127.0.0.1:18090/realms/localai-rag/protocol/openid-connect/logout",
        "scopes": ["openid", "profile", "email"],
        "redirect_path": "/",
        "post_logout_redirect_path": "/"
      }
    }
  }
}
```

## 6. Troubleshooting

If the UI can log in but the API returns `401 invalid_token` or `401 invalid_audience`:
- decode the access token payload (without sharing the token) and verify `iss` and `aud`,
- confirm the Audience mapper is applied to tokens of the `localai-rag-ui` client,
- ensure the app config uses the correct realm issuer and JWKS URL.

