# Authorization Contract (DEV → PROD)

**Version:** 0.4  
**Date:** 2026-02-03  
**Status:** transitional DEV document prepared for PROD migration

## 1. Purpose
This document defines:
1. The target authorization model and access management.
2. The current DEV implementation (temporary).
3. How permissions are passed to pipelines and retrieval.
4. The migration path to production.

The backend treats this document as source of truth. The frontend treats authorization as an input mechanism (the `Authorization` header).

## 2. Definitions
1. **Authentication**: identifying the user based on a token.
2. **Authorization**: deciding what the user can access.
3. **UserId**: internal user identifier.
4. **Group**: permission group (a user can belong to many groups).
5. **ACL**: access tags for data (`acl_tags_any`).
6. **Classification**: classification labels (`classification_labels_all`).
7. **Pipeline**: a defined workflow for query processing.
8. **Session**: conversation tracking (independent of authorization).
9. **UserAccessContext**: resolved permissions passed to pipeline and retrieval.

## 3. Global Principles
1. A user can be **anonymous** (no authorization).
2. A user can be **authenticated** (`Authorization: Bearer ...`).
3. Session is always tracked (`session_id`), regardless of auth status.
4. Permissions come from groups, and users inherit group permissions.
5. A user can be treated as a group (common PostgreSQL/Unix pattern).
6. Pipelines and retrieval do not implement login; they receive resolved permissions.

## 4. Authorization Model (Target)
### 4.1 Token and UserId
1. Each request may include `Authorization: Bearer <token>`.
2. Token is validated by the auth layer.
3. Token is mapped to `user_id` and group list.

### 4.2 Group Permissions
Groups define:
1. `allowed_pipelines` — pipeline list accessible to the user.
2. `allowed_commands` — functional commands available in UI/Backend.
3. `acl_tags_any` — ACL tags using OR semantics.
4. `classification_labels_all` — classification labels using ALL/subset semantics.

### 4.3 Inheritance
1. Users inherit permissions from all groups they belong to.
2. If a user has no group, the `anonymous` group is assigned automatically.

### 4.4 `acl_tags_any` Semantics (MUST)
1. `acl_tags_any` uses logical OR.
2. A document is visible if it has at least one ACL tag from the user context.
3. Empty ACL on a document is allowed and treated as public.
4. Importer MUST always set ACL; missing field is treated as empty list.

Clarification:
1. Empty ACL means “public” and must be returned even when `acl_tags_any` is present.
2. A document is visible if it has no ACL tags or shares at least one tag with `acl_tags_any`.
3. Extra ACL tags on a document do not block access as long as one tag matches.

### 4.5 `classification_labels_all` Semantics (MUST)
1. `classification_labels_all` uses ALL/subset semantics.
2. A document is visible only if all its classification labels are contained in the user context.
3. Empty classification on a document is allowed.
4. Importer MUST always set classification; missing field is treated as empty list.
5. Label hierarchy (e.g., `critical` implies `restricted`) is not inferred; it must be explicit in group definitions.

Clarification:
1. If the document has labels, they must be a subset of `classification_labels_all`.
2. Empty document classification labels are allowed.
3. If the document contains any label not in `classification_labels_all`, it is not visible.

### 4.6 Multi‑Group Users
Permissions are merged by union:
1. `allowed_pipelines` = union of all group pipelines.
2. `allowed_commands` = union of all group commands.
3. `acl_tags_any` = union of all group ACL tags.
4. `classification_labels_all` = union of all group classification labels.

### 4.7 `allowed_pipelines` Matching
1. Exact name match only.
2. No prefixes, globbing, or regex.

### 4.8 `owner_id` and `source_system_id` (Future)
1. `owner_id` is optional metadata; not enforced yet.
2. `source_system_id` is optional metadata and may be used as an exact‑match filter.

## 5. Current Implementation (DEV)
### 5.1 Fake Login (Frontend)
1. When enabled, frontend sends: `Authorization: Bearer dev-user:dev-user-1`.
2. When disabled, no header is sent and the user is anonymous.

### 5.2 Authorization Provider (Backend)
Provider:
1. `server/auth/user_access.py`
2. Interface: `UserAccessProvider.resolve(user_id, token, session_id)`
3. DEV implementation: `DevUserAccessProvider`

Returned object:
```python
UserAccessContext(
  user_id: Optional[str],
  is_anonymous: bool,
  group_ids: List[str],
  allowed_pipelines: List[str],
  allowed_commands: List[str],
  acl_tags_any: List[str],
  classification_labels_all: List[str],
  owner_id: Optional[str] = None
)
```

### 5.3 Group Policies JSON
Policies are stored in:
1. `config/auth_policies.json`

If a group in the token does not exist:
1. It is treated as empty.
2. User retains only `anonymous` permissions.
3. A warning should be logged.

### 5.4 Server Logic
In `query_server_dynamic.py`:
1. Server resolves `UserAccessContext`.
2. If `allowed_pipelines` does not include the requested pipeline → **403**.
3. `acl_tags_any` → `retrieval_filters.acl_tags_any`.
4. `classification_labels_all` → `retrieval_filters.classification_labels_all`.
5. Retrieval and graph providers respect these filters.

### 5.5 Cache / Performance (DEV/PROD)
1. DEV: no permission cache (resolved per request).
2. PROD: cache recommended (TTL 1–5 minutes) token → `UserAccessContext`.

### 5.6 Session and Audit
1. `session_id` is independent from authorization.
2. Logs should include both `session_id` and `user_id` (if available).

### 5.7 Logging Failed Authorization
Every **403** due to pipeline access must be logged with:
1. `pipeline_requested`
2. `user_id` or `anonymous`
3. `session_id`

## 6. Request Flow (DEV)
1. Frontend sends `POST /search` with optional `Authorization`.
2. Server resolves `UserAccessContext`.
3. Server filters pipelines.
4. Server runs pipeline with `retrieval_filters`.
5. Retrieval and graph filter data by `acl_tags_any` and `classification_labels_all`.

## 7. Token Format (DEV)
```
Authorization: Bearer dev-user:<user_id>
```
This is DEV‑only and not secure.

## 8. Production Direction
1. Replace `DevUserAccessProvider` with DB/IAM provider.
2. Remove `config/auth_policies.json`.
3. Remove Fake Login in frontend.
4. Permissions managed by admins or IAM.

`UserAccessContext` interface remains stable between DEV and PROD.

### 8.1 DEV vs PROD Summary
| Element | DEV | PROD (plan) |
| --- | --- | --- |
| Provider | `DevUserAccessProvider` | DB/IAM provider |
| Policy source | `config/auth_policies.json` | DB/IAM |
| Token format | `dev-user:<user_id>` | JWT/OAuth2/OIDC |
| Fake login | Yes | No |
| Permission updates | Manual JSON | Admin panel / API |

## 9. Architecture Decisions
1. Authorization is centralized in server/auth.
2. Pipeline and retrieval stay auth‑agnostic.
3. Groups are the primary ACL mechanism.
4. Session is independent of authorization.

## 10. Frontend Role
1. Frontend is not a source of truth for permissions.
2. Frontend receives only allowed consultants/pipelines via `/app-config`.
3. Frontend never receives full `UserAccessContext`.
4. Enforcement is server‑side only.

## 11. Minimum Consistency Requirements
1. If pipeline is not allowed, request ends with **403**.
2. `acl_tags_any` and `classification_labels_all` must be applied in every retrieval stage.
3. UI should display only consultants allowed for the user.

## 12. Rate Limiting / Anti‑abuse (Recommendation)
1. Anonymous access should be rate limited (e.g., RPM / IP throttling).
2. Production should apply global rate limiting.
3. Recommended: ingress / API Gateway, optionally app‑level limit for `/search`.

## 13. Risks (DEV)
1. Fake login is not secure.
2. `config/auth_policies.json` is prone to manual errors.
3. No cache can become a bottleneck under load.

