# Permissions and Identity Provider Policy
Wiki: [Home](../../wiki/Home.md)


This document describes how identity, permissions, and access control are connected in the application.

## Identity Provider (OIDC)
The `auth.oidc.resource_server` section in `config.json` defines JWT validation for the API:
- `enabled`: whether JWT validation is enforced
- `issuer` (from `auth.oidc.issuer`)
- `jwks_url`, `audience`, `algorithms`
- `required_claims`

When enabled, incoming requests must present a valid token.

### Keycloak notes (audience mapping)
If you use Keycloak, make sure that access tokens obtained by the browser UI client include the API audience
in the `aud` claim. Otherwise the API will reject the token.

See:
- `docs/howto/keycloak_oidc_pkce_setup.md`

## Permissions Configuration
The `permissions` section in `config.json` defines global security behavior:
- `security_enabled`: master toggle for security enforcement
- `acl_enabled`: toggles ACL tag filtering
- `require_travel_permission`: affects graph expansion travel rule
- `security_model.kind`: e.g., `clearance_level` or `labels_universe_subset`

## Access Context Derivation
User access context is derived from:
- JWT claims (via identity provider)
- SQL security tables when the `security` schema/database is present and populated
- Fallback `security_conf/auth_policies.json` + `security_conf/claim_group_mappings.json`
  when SQL security is intentionally absent or unavailable in non-production profiles

The resulting access context drives retrieval filters:
- `acl_tags_any`
- `classification_labels_all`
- clearance level (if configured)

## SQL Security Source
When `config.sql` is enabled:
- the server always uses SQL for chat history,
- the server tries to use SQL for security policies,
- if the SQL security schema exists but is empty, it is bootstrapped from `security_conf/*`,
- if the SQL security schema is missing entirely, the server falls back to `security_conf/*`,
- in `APP_PROFILE=prod`, a partially populated or broken SQL security schema is a hard startup error.

## Enforcement
The access context is enforced in:
1. Retrieval (`search_nodes`, `fetch_node_texts`)
2. Graph expansion
3. Any security-critical pipeline step

Dynamic pipeline directives must **not** override security filters.

## Notes
- Empty ACL on a document is treated as public.
- Classification labels must be a subset of user allowed labels.
- Doc level is enforced only in clearance-based security model.
