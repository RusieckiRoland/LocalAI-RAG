# Authorization Contract (DEV → PROD)

**Version:** 0.4  
**Date:** 2026-02-03  
**Status:** transitional document (DEV), prepared for PROD migration

## 1. Purpose
This document describes:
- the target authorization model and access management,
- the current development (temporary) implementation,
- how permissions are passed into the pipeline and retrieval layer,
- the roadmap towards production.

The backend is the source of truth. The frontend treats authorization as an input mechanism (the `Authorization` header).

## 2. Terms and definitions
- **Authentication** – identifying the user based on a token.
- **Authorization** – deciding what the user can access.
- **UserId** – internal user identifier.
- **Group** – a permission group (a user can belong to multiple groups).
- **ACL** – list of access tags for data (`acl_tags_all`).
- **Pipeline** – a defined workflow for processing a query.
- **Session** – a conversation tracking mechanism (independent from authorization).
- **UserAccessContext** – the resolved access context passed into the pipeline and retrieval layer.

## 3. Core principles
1. A user can act as **anonymous** (no authorization).
2. A user can act as **authenticated** (token `Authorization: Bearer ...`).
3. Regardless of anonymous/authenticated status, **sessions are always tracked** (`session_id`).
4. Permissions come from **groups**, and the user **inherits** group permissions.
5. A user can be treated as a group (standard pattern like PostgreSQL/Unix).
6. Pipeline and retrieval **do not implement login** – they receive resolved permissions.

## 4. Authorization model (target)
### 4.1. Token and UserId
- Each request may include `Authorization: Bearer <token>`.
- The token is validated by the auth layer.
- The token is mapped to `user_id` and a list of groups.

### 4.2. Group permissions
A group determines:
- `allowed_pipelines` – the list of pipelines available to the user.
- `acl_tags_all` – ACL tags that must be satisfied in retrieval/graph.

### 4.3. Inheritance rule
- The user inherits permissions from all groups they belong to.
- If the user has no groups, the `anonymous` group is assigned automatically.

### 4.4. `acl_tags_all` semantics (MUST)
- `acl_tags_all` means **logical AND**: all tags must be satisfied.
- A document/record is accessible **only if** it contains **all** tags from `acl_tags_all`.
- Tag negation is **not supported** (no `NOT`, no exclusions).

### 4.5. User in multiple groups
Permissions are **unioned**:
- `allowed_pipelines` = union of `allowed_pipelines` across all user groups.
- `acl_tags_all` = union of `acl_tags_all` across all user groups.

### 4.6. `allowed_pipelines` matching
- `allowed_pipelines` are **exact pipeline names** (exact match).
- No prefixes, glob patterns, or regex are used.

## 5. Current implementation (DEV)
### 5.1. Fake login (frontend)
The frontend provides a **Fake Login** button:
- When enabled → sends header:
  `Authorization: Bearer dev-user:dev-user-1`
- When disabled → no header, the user is treated as anonymous.

### 5.2. Authorization provider (backend)
The server uses an access provider:
- `server/auth/user_access.py`
- Interface: `UserAccessProvider.resolve(user_id, token, session_id)`
- DEV implementation: `DevUserAccessProvider`

The provider returns:
```python
UserAccessContext(
  user_id: Optional[str],
  is_anonymous: bool,
  group_ids: List[str],
  allowed_pipelines: List[str],
  acl_tags_all: List[str]
)
```

### 5.3. Group policies in JSON
Policies are stored in a dedicated file:
- `config/auth_policies.json`

Example (current):
```json
{
  "groups": {
    "anonymous": {
      "allowed_pipelines": [
        "marian_rejewski_code_analysis_base"
      ],
      "acl_tags_all": []
    },
    "authenticated": {
      "allowed_pipelines": [
        "marian_rejewski_code_analysis_base",
        "ada_uml_base",
        "branch_compare_base"
      ],
      "acl_tags_all": [
        "security",
        "finance"
      ]
    }
  }
}
```

If a group referenced in a token does not exist in `auth_policies.json`:
- the group is treated as empty,
- the user retains only permissions from `anonymous`,
- a **warning should be logged**.

### 5.4. Server logic
In `query_server_dynamic.py`:
- The server resolves `UserAccessContext`.
- If `allowed_pipelines` does not include the requested pipeline → **403**.
- `acl_tags_all` is passed as `retrieval_filters.acl_tags_all`.
- `retrieval_filters` are respected by retrieval and graph providers.

### 5.5. Cache / performance (DEV/PROD)
- DEV: no caching (resolved per request).
- PROD: caching is recommended (e.g., TTL 1–5 minutes) token → `UserAccessContext`.

### 5.6. Session and audit
- `session_id` is independent from authorization.
- Logs should include **both** `session_id` and `user_id` (if available),
  to enable auditing and abuse detection.

### 5.7. Logging unauthorized attempts
Each **403** due to disallowed pipeline should be logged with:
- `pipeline_requested`
- `user_id` or `anonymous`
- `session_id`

## 6. Request flow (DEV)
1. The frontend sends `POST /search` with optional `Authorization`.
2. The server resolves `UserAccessContext`.
3. The server filters available pipelines.
4. The server runs the pipeline with `retrieval_filters`.
5. Retrieval and graph filter data based on `acl_tags_all`.

## 7. Token format (DEV)
```
Authorization: Bearer dev-user:<user_id>
```

In PROD the token will be validated (e.g., JWT/OAuth) and mapped to user and groups in DB.
**Note:** `dev-user:<user_id>` is DEV-only and not secure.

## 8. Roadmap to PROD
- `DevUserAccessProvider` will be replaced by a database-backed provider.
- `config/auth_policies.json` will be removed.
- The frontend will stop using fake login.
- Permissions will be managed by admins or an IAM system.

The `UserAccessContext` interface remains stable between DEV and PROD.

### 8.1. DEV vs PROD (summary)
| Element | DEV | PROD (plan) |
| --- | --- | --- |
| Provider | `DevUserAccessProvider` | Database / IAM provider |
| Policy source | `config/auth_policies.json` | DB / external IAM |
| Token format | `dev-user:<user_id>` | JWT / OAuth2 / OIDC |
| Fake login | Yes | No |
| Permissions changes | Manual JSON edits | Admin panel / API |

## 9. Architectural decisions
- Authorization is **centralized** (server/auth).
- Pipeline and retrieval are **clean** (no login logic).
- Groups are the primary ACL mechanism.
- Session (`session_id`) is independent from authorization.

## 10. Frontend role and permissions exposure
- The frontend is not a source of truth for permissions.
- The frontend may receive **only the list of allowed consultants/pipelines** via `/app-config`.
- The frontend **does not receive** the full `UserAccessContext`.
- All permission enforcement happens on the server.

## 11. Minimal consistency requirements
- If a pipeline is not allowed, the request must end with **403**.
- `acl_tags_all` must be applied in every retrieval (search + graph).
- The UI should show only consultants allowed for the user.

## 12. Rate limiting / anti‑abuse (recommendation)
- Anonymous access should be limited (e.g., RPM / IP throttling).
- In production, global rate limiting is recommended for all users.
- Recommended implementation: **ingress / API Gateway**, optionally with an app‑level limit for `/search`.

## 13. Risks and assumptions (DEV)
- Fake login is not secure – functional testing only.
- `config/auth_policies.json` is prone to manual errors (no schema validation).
- Lack of caching can become a bottleneck under high traffic.
