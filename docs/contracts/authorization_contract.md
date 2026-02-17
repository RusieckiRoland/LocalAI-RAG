# Authorization Contract (DEV → PROD)

**Version:** 0.7  
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
- **ACL (department/group tags)** – list of access tags for data (`acl_tags_any`).
- **Classification labels** – security labels that must be fully satisfied (`classification_labels_all`).
- **User level** – numeric clearance level derived from groups (`user_level`).
- **Security model** – selected authorization model in `config.json` (`labels_universe_subset` or `clearance_level`).
- **Permissions config** – the `permissions` block in `config.json` that enables/disables security and ACL and selects a model.
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
### 4.0. Global permissions config (SINGLE source of truth)
All authorization behavior is driven by `config.json`:
```json
"permissions": {
  "security_enabled": true,
  "acl_enabled": true,
  "security_model": {
    "kind": "labels_universe_subset",
    "labels_universe_subset": {
      "doc_labels_field": "classification_labels",
      "user_labels_source": "claim",
      "user_labels_claim": "labels",
      "allow_unlabeled": true,
      "classification_labels_universe": ["public", "internal", "restricted", "critical"]
    }
  }
}
```
Rules:
- `security_enabled=false` → **no security filtering** (warning logged).
- `acl_enabled=false` → **ACL not enforced** and importer must not write `acl_allow`.
- `require_travel_permission=true` → graph expansion cannot "travel through" unauthorized nodes (details in 4.13).
- `security_model.kind` chooses **exactly one** model:
  - `labels_universe_subset` **or**
  - `clearance_level`.

### 4.1. Token and UserId
- Each request may include `Authorization: Bearer <token>`.
- The token is validated by the auth layer.
- The token is mapped to `user_id` and a list of groups.

### 4.2. Group permissions
A group determines:
- `allowed_pipelines` – the list of pipelines available to the user.
- `allowed_commands` – the list of functional commands available to the user (UI/Backend).
- `acl_tags_any` – access tags used with OR semantics in retrieval/graph.
- `classification_labels_all` – classification labels used with ALL/subset semantics in retrieval/graph.
- `user_level` – numeric clearance level (used in `clearance_level` model).
- `owner_id` – optional ownership metadata.
- `source_system_id` – optional multi-source metadata.

> [!WARNING]
> The system uses **either** `user_level` **or** `classification_labels_all` for security enforcement (depending on `permissions.security_model.kind`), or **neither** when `permissions.security_enabled=false`. Both are not active at the same time.


### 4.3. Inheritance rule
- The user inherits permissions from all groups they belong to.
- If the user has no groups, the `anonymous` group is assigned automatically.

### 4.4. `acl_tags_any` semantics (MUST) – when `permissions.acl_enabled=true`
- `acl_tags_any` means **logical OR**.
- A document/record is accessible when it has at least one ACL tag from user/group context.
- Empty document ACL tags are allowed (do not block access).
- If `permissions.acl_enabled=false`, ACL is **not enforced**, and importer **must not** write `acl_allow`.
- Importers MUST always set ACL fields **only when ACL is enabled**.
- If a document has extra ACL tags, it is still visible as long as it shares **at least one** tag with `acl_tags_any`.

### 4.5. `classification_labels_all` semantics (MUST) – when `security_model.kind=labels_universe_subset`
- `classification_labels_all` means **ALL/subset check** (`doc_labels ⊆ user_labels`).
- Empty document classification labels are allowed (do not block access).
- Importers MUST set classification fields when this model is active; missing fields are treated as empty lists.
- If the document has any label **not present** in `classification_labels_all`, it is not visible.
- Label hierarchy is **not inferred** by the engine.
Additional constraints:
- `classification_labels_universe` is a **finite list** defined in config.
- Any label **outside the universe** is considered invalid (should be blocked or flagged by consistency checks).
- Server-side filtering uses Weaviate predicates (no Python post-filtering).

### 4.6. `clearance_level` semantics (MUST) – when `security_model.kind=clearance_level`
- Each document may have an integer `doc_level` (configurable field name).
- User has `user_level` derived from group policy.
- A document is accessible when `doc_level <= user_level`.
- If `allow_missing_doc_level=true`, documents without `doc_level` are treated as public.
Additional constraints:
- `doc_level` **must be an integer** in storage and in import payloads.
- If `doc_level` is missing and `allow_missing_doc_level=false` → document is blocked.

### 4.7. User in multiple groups
Permissions are **unioned**:
- `allowed_pipelines` = union of `allowed_pipelines` across all user groups.
- `allowed_commands` = union of `allowed_commands` across all user groups.
- `acl_tags_any` = union of `acl_tags_any` across all user groups.
- `classification_labels_all` = union of `classification_labels_all` across all user groups.
- `user_level` = **max** across all user groups.

### 4.8. `allowed_pipelines` matching
- `allowed_pipelines` are **exact pipeline names** (exact match).
- No prefixes, glob patterns, or regex are used.

### 4.9. `owner_id` and `source_system_id` (future use)
- `owner_id` is optional metadata for ownership workflows (e.g., ownership-based classification edits).
- `owner_id` is not enforced yet in runtime authorization decisions.
- `source_system_id` is optional metadata for multi-source retrieval (code/docs/pdf/etc.).
- `source_system_id` may be used as an additional exact-match scope filter when requested.

### 4.10. Security model selection (GLOBAL)
The system uses **exactly one** security model at runtime:
- `labels_universe_subset` **or**
- `clearance_level`

The selection is controlled by `config.json`:
```json
"permissions": {
  "security_enabled": true,
  "acl_enabled": true,
  "security_model": { "kind": "labels_universe_subset" }
}
```

When `permissions.security_enabled=false`, the server logs a warning and **does not enforce** security filters.

### 4.11. Data requirements by model (IMPORTER contract)
**If `security_model.kind=labels_universe_subset`:**
- Importer MUST write `classification_labels` for each doc (can be empty list).
- Labels MUST be within `classification_labels_universe`.
- `classification_labels` must be stored in Weaviate schema.

**If `security_model.kind=clearance_level`:**
- Importer MUST write `doc_level` (integer) for each doc, unless `allow_missing_doc_level=true`.
- `doc_level` must be stored in Weaviate schema.

**If `permissions.acl_enabled=true`:**
- Importer MUST write `acl_allow` (list of strings) for each doc (can be empty).

**If `permissions.acl_enabled=false`:**
- Importer MUST NOT write `acl_allow`.

### 4.12. Consistency checks (startup)
On server startup, the system validates:
- `permissions.security_enabled` and model selection.
- Weaviate schema contains required fields (`classification_labels` or `doc_level`, plus `acl_allow` if ACL enabled).
- `auth_policies` group definitions do not reference labels outside `classification_labels_universe`.
- Claim-to-group mappings reference existing group IDs.
Failures/warnings must be logged clearly before any queries are processed.

### 4.13. Graph expansion travel permission (GLOBAL)
This flag controls whether **unauthorized nodes block traversal** during dependency tree expansion.

Config:
```json
"permissions": {
  "require_travel_permission": true
}
```

Rules:
- `require_travel_permission=true`:
  - if a node is not visible to the user, **any nodes discovered through it are also hidden**,
    even if they would be visible on their own.
- `require_travel_permission=false`:
  - only the unauthorized nodes are removed,
  - nodes connected through them can still appear if they are individually visible.

## 5. Current implementation (DEV/PROD boundary)
### 5.1. Fake login (frontend)
The frontend provides a **Fake Login** button:
- When enabled → sends header:
  `Authorization: Bearer dev-user:dev-user-1`
- When disabled → no header, the user is treated as anonymous.

### 5.2. Authorization provider (backend)
The server uses an access provider:
- `server/auth/user_access.py`
- Interface: `UserAccessProvider.resolve(user_id, token, session_id, claims)`
- DEV implementation: `DevUserAccessProvider`

The provider returns:
```python
UserAccessContext(
  user_id: Optional[str],
  is_anonymous: bool,
  group_ids: List[str],
  allowed_pipelines: List[str],
  allowed_commands: List[str],
  acl_tags_any: List[str],
  classification_labels_all: List[str],
  user_level: Optional[int],
  owner_id: Optional[str] = None,
  source_system_id: Optional[str] = None
)
```

### 5.3. Group policies provider (interface)
There is an **interface** for group policies:
- `server/auth/policies_provider.py`
- default implementation reads `config/auth_policies.json`

### 5.4. Group policies in JSON
Policies are stored in a dedicated file:
- `config/auth_policies.json`

Example (current):
```json
{
  "groups": {
    "anonymous": {
      "allowed_pipelines": [
        "ada"
      ],
      "allowed_commands": [],
      "acl_tags_any": [],
      "classification_labels_all": []
    },
    "authenticated": {
      "allowed_pipelines": [
        "rejewski",
        "ada",
        "shannon"
      ],
      "allowed_commands": [
        "showDiagram",
        "saveDiagram",
        "ea_export"
      ],
      "acl_tags_any": [
        "security",
        "finance"
      ],
      "classification_labels_all": ["public", "internal", "restricted", "critical"]
    },
    "clearance:public": {
      "user_level": 0,
      "allowed_pipelines": [],
      "allowed_commands": [],
      "acl_tags_any": [],
      "classification_labels_all": []
    },
    "clearance:internal": {
      "user_level": 10,
      "allowed_pipelines": [],
      "allowed_commands": [],
      "acl_tags_any": [],
      "classification_labels_all": []
    },
    "clearance:restricted": {
      "user_level": 20,
      "allowed_pipelines": [],
      "allowed_commands": [],
      "acl_tags_any": [],
      "classification_labels_all": []
    },
    "clearance:critical": {
      "user_level": 30,
      "allowed_pipelines": [],
      "allowed_commands": [],
      "acl_tags_any": [],
      "classification_labels_all": []
    }
  }
}
```

Optional mapping from JWT claims to groups:
```json
"claim_group_mappings": [
  {
    "claim": "user_level",
    "value_map": {
      "0": "clearance:public",
      "10": "clearance:internal",
      "20": "clearance:restricted",
      "30": "clearance:critical"
    }
  }
]
```

If a group referenced in a token does not exist in `auth_policies.json`:
- the group is treated as empty,
- the user retains only permissions from `anonymous`,
- a **warning should be logged**.

### 5.5. Server logic
In `query_server_dynamic.py`:
- The server resolves `UserAccessContext`.
- If `allowed_pipelines` does not include the requested pipeline → **403**.
- If `snapshot_set_id` is provided, snapshot membership is validated:
  - primary snapshot (`snapshot_id`) must belong to set
  - secondary snapshot (`snapshot_id_b`, compare mode) must belong to set
  - violation → **400**
- `acl_tags_any` is passed as `retrieval_filters.acl_tags_any` **only if** `permissions.acl_enabled=true`.
- `classification_labels_all` is passed as `retrieval_filters.classification_labels_all` **only when** `security_model.kind=labels_universe_subset`.
- `user_level` (if present) is passed as `retrieval_filters.user_level` **only when** `security_model.kind=clearance_level`.
- `owner_id` and `source_system_id` are optional filters/metadata and may be included in `retrieval_filters` when needed.
- `retrieval_filters` are respected by retrieval and graph providers.

### 5.5.1. Server-side filtering guarantee
Security filtering MUST be applied in Weaviate queries (not post-filtered in Python).
Any deviation (e.g., temporary fallbacks) must be logged and treated as a blocking issue.

Endpoint exposure by mode:
- Development endpoints are controlled by config/env:
  - `config.json`: `"developement": true|false`
  - env override: `APP_DEVELOPMENT=1|0`
- When disabled, `/app-config/dev`, `/search/dev`, `/query/dev` return `404`.
- Production endpoints remain available: `/app-config/prod`, `/search/prod`, `/query/prod`.

Bearer enforcement:
- `/app-config/prod`, `/search/prod`, `/query/prod` always require bearer validation.
- `/auth-check/prod` is a lightweight bearer validation endpoint for diagnostics.

### 5.6. Cache / performance (DEV/PROD)
- DEV: no caching (resolved per request).
- PROD: caching is recommended (e.g., TTL 1–5 minutes) token → `UserAccessContext`.

### 5.7. Session and audit
- `session_id` is independent from authorization.
- Logs should include **both** `session_id` and `user_id` (if available),
  to enable auditing and abuse detection.

### 5.8. Logging unauthorized attempts
Security incidents are logged with tag `security_abuse` (log payload prefix: `[security_abuse]`), including:
- invalid/missing bearer on protected endpoints (**401**),
- expired/invalid JWT (**401**),
- pipeline access violation (**403**),
- snapshot not in snapshot set (**400**).
  - also for secondary snapshot (`snapshot_id_b`) when compare mode is used.

Each entry should include:
- `reason`
- `status`
- `path`
- `remote`
- `pipeline`
- `user_id` or `anonymous`
- `session_id`

## 6. Request flow
1. The frontend sends `POST /search/dev` (development) or `POST /search/prod` (production).
2. The server resolves `UserAccessContext`.
3. The server filters available pipelines.
4. The server runs the pipeline with `retrieval_filters`.
5. Retrieval and graph filter data based on `acl_tags_any` and `classification_labels_all`.

## 7. Token validation
### 7.1 DEV fallback
```
Authorization: Bearer dev-user:<user_id>
```

**Note:** `dev-user:<user_id>` is DEV-only and not secure.

### 7.2 PROD (current)
For `prod` endpoints, token validation follows this order:
1. If IDP auth is active (`identity_provider.enabled=true` and required fields present), validate JWT using `issuer`, `audience`, and `jwks_url`.
2. Otherwise fallback to `Authorization: Bearer <API_TOKEN>` exact match.

IDP activation can be forced/disabled with `IDP_AUTH_ENABLED=1|0`.

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
- If `snapshot_set_id` and `snapshot_id` are provided, membership must be validated; invalid pair must end with **400**.
- If `snapshot_id_b` is provided, its membership in `snapshot_set_id` must also be validated; invalid pair must end with **400**.
- `acl_tags_any` and `classification_labels_all` must be applied in every retrieval (search + graph).
- The UI should show only consultants allowed for the user.

## 12. Rate limiting / anti‑abuse (recommendation)
- Anonymous access should be limited (e.g., RPM / IP throttling).
- In production, global rate limiting is recommended for all users.
- Recommended implementation: **ingress / API Gateway**, optionally with an app‑level limit for `/search`.

## 13. Risks and assumptions (DEV)
- Fake login is not secure – functional testing only.
- `config/auth_policies.json` is prone to manual errors (no schema validation).
- Lack of caching can become a bottleneck under high traffic.
