# Permissions and Identity Provider Policy

This document describes how identity, permissions, and access control are connected in the application.

## Identity Provider
The `identity_provider` section in `config.json` defines:
- `enabled`: whether JWT validation is enforced
- `issuer`, `jwks_url`, `audience`, `algorithms`
- `required_claims`

When enabled, incoming requests must present a valid token.

## Permissions Configuration
The `permissions` section in `config.json` defines global security behavior:
- `security_enabled`: master toggle for security enforcement
- `acl_enabled`: toggles ACL tag filtering
- `require_travel_permission`: affects graph expansion travel rule
- `security_model.kind`: e.g., `clearance_level` or `labels_universe_subset`

## Access Context Derivation
User access context is derived from:
- JWT claims (via identity provider)
- Optional `auth_policies.json` (group/role mappings)

The resulting access context drives retrieval filters:
- `acl_tags_any`
- `classification_labels_all`
- clearance level (if configured)

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

