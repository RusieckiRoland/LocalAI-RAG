# Before Production Checklist

This document lists what must be completed before moving to production. It focuses on areas intentionally simplified in DEV and that **must** be replaced in PROD.

## 1. Authentication and Authorization
**DEV state**
1. `DevUserAccessProvider` assigns `authenticated` group to any token `Bearer dev-user:<id>`.
2. Policies are in `config/auth_policies.json`.

**Required before production**
1. Integrate a real identity provider (OIDC/Keycloak/LDAP/SSO).
2. Validate tokens cryptographically (signature, expiry, issuer, audience).
3. Map token groups to application groups.
4. If token only provides `user_id`, add DB mapping `user_id → groups`.
5. Disable Fake Login in frontend.

**Related files**
1. `server/auth/user_access.py`
2. `config/auth_policies.json`
3. `frontend/Rag.html`

## 2. Permission Policies (pipelines / commands)
**DEV state**
1. `allowed_pipelines`, `acl_tags_any`, `classification_labels_all` from `auth_policies.json`.

**Required before production**
1. Move policies to target source (DB / IAM).
2. Keep separation:
   - `allowed_pipelines` → pipeline access
   - `acl_tags_any` → data access filtering (OR)
   - `classification_labels_all` → classification filtering (ALL/subset)
   - `allowed_commands` → UI command permissions (if enabled)

**Related files**
1. `server/auth/user_access.py`
2. `server/pipelines/pipeline_access.py`
3. `code_query_engine/query_server_dynamic.py`

## 3. Data and Retrieval (ACL)
**DEV state**
1. `acl_tags_any` and `classification_labels_all` passed to retrieval filters.

Clarification:
1. Empty ACL means “public”.
2. A document is visible if it has no ACL tags or shares at least one tag with `acl_tags_any`.
3. Classification labels must be a subset of `classification_labels_all` (empty classification allowed).
4. Importer MUST always set ACL/classification; missing fields are treated as empty lists.

**Required before production**
1. Confirm and document ACL semantics (OR/ALL) consistently.
2. Ensure every retrieval and graph stage applies ACL filters.
3. Add security tests (access only to allowed chunks).

**Related files**
1. `docs/contracts/authorization_contract.md`
2. `code_query_engine/pipeline/providers/weaviate_retrieval_backend.py`
3. `code_query_engine/pipeline/providers/weaviate_graph_provider.py`

## 4. Snapshots / SnapshotSet
**DEV state**
1. `snapshot_set_id` comes from YAML pipeline.
2. Snapshots are loaded from Weaviate.

**Required before production**
1. Ensure SnapshotSets are consistent in Weaviate.
2. Add monitoring for `/app-config` errors (missing SnapshotSet is a hard error).
3. Define SnapshotSet update process.

**Related files**
1. `server/snapshots/snapshot_registry.py`
2. `server/pipelines/pipeline_snapshot_store.py`
3. `server/app_config/app_config_service.py`

## 5. Frontend Contract
**DEV state**
1. Contract defined in `docs/contracts/frontend_contract.md`.

**Required before production**
1. Block access to mock server.
2. Ensure UI respects `snapshotPolicy`.
3. Ensure UI does not send duplicate `snapshots[]` in compare mode.

**Related files**
1. `docs/contracts/frontend_contract.md`
2. `frontend/Rag.html`

## 6. Logging and Monitoring
**Required**
1. Authorization and retrieval error logs.
2. Alerts for missing snapshots or unknown pipelines.
3. Monitoring `/app-config` and `/search` errors.

**Related files**
1. `common/logging_setup.py`
2. `code_query_engine/query_server_dynamic.py`

## 7. Environment Configuration
**Required**
1. Store secrets outside repo.
2. Validate production `config.json`.
3. Validate Weaviate config.

---

## Summary
Before production, all DEV shortcuts must be replaced with real mechanisms:
1. Real login and group mapping.
2. Permission policies in DB/IAM.
3. Consistent ACL filtering.
4. Monitoring and alerts.

Use this as a checklist and expand as the system evolves.
