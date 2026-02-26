# Frontend Integration Contract (HTTP + UI)

## 1. Purpose
This document defines the complete contract needed to build any web frontend that works with this server:
- startup configuration,
- consultant and snapshot selection,
- query execution,
- trace streaming and cancellation,
- chat history,
- multilingual behavior.

The server is the source of truth.

---

## 2. Terminology
- Consultant: UI card selected by user. It maps to a backend pipeline.
- Pipeline: backend execution flow.
- Snapshot set: a named set of snapshots for one pipeline/repository.
- Snapshot: one concrete version inside snapshot set.
- Neutral language: canonical model language used by pipeline internals.
- Translated language: UI language that can trigger in/out translation.

---

## 3. Environment and endpoint matrix

### 3.1 Runtime modes
- The server exposes a single set of endpoints.
- Runtime config file is selected by `APP_PROFILE`:
  - `APP_PROFILE=dev` uses `config.dev.json`
  - `APP_PROFILE=prod` uses `config.prod.json`
  - `APP_PROFILE=test` uses `config.test.json`
- Whether endpoints accept requests without a valid bearer depends only on `DEV_ALLOW_NO_AUTH`:
  - `DEV_ALLOW_NO_AUTH=true` allows running without a real security token **only** when `APP_PROFILE!=prod`, but still requires a fake login header: `Authorization: Bearer dev-user:<user_id>`.
  - In all other cases bearer auth is required.
- If `APP_PROFILE` is not set, it defaults to `prod`.

In no-auth mode, the UI should present a fake login screen to select a user from `config.dev.json: fake_users` (users represent JWT-like claims).

### 3.2 Endpoint matrix
- `GET /health`
- `GET /app-config`
- `POST /search`
- `POST /query` (same behavior as `/search`)
- `GET /pipeline/stream?run_id=<id>`
- `POST /pipeline/cancel`
- `GET /auth-check`
- `GET /chat-history/sessions`
- `POST /chat-history/sessions`
- `GET /chat-history/sessions/{sessionId}`
- `PATCH /chat-history/sessions/{sessionId}`
- `DELETE /chat-history/sessions/{sessionId}`
- `GET /chat-history/sessions/{sessionId}/messages`
- `POST /chat-history/sessions/{sessionId}/messages`

---

## 4. Authentication and headers

### 4.1 Bearer auth requirement
- When `DEV_ALLOW_NO_AUTH` is **not** enabled, protected endpoints require `Authorization: Bearer <token>`.
- Validation mode:
  - Identity Provider JWT (if enabled).
  - Optional static API token (`API_TOKEN`) may be supported for **service-to-service** clients only (restricted network).
    - It must NOT be used by browser/SPA clients.
For the browser UI, use OpenID Connect Authorization Code Flow with PKCE (e.g. Keycloak).

### 4.2 DEV_ALLOW_NO_AUTH mode (explicit local no-auth)
- Enabled only when `DEV_ALLOW_NO_AUTH=true` and `APP_PROFILE!=prod`.
- The server does not require a real security token, but still requires a fake login header: `Authorization: Bearer dev-user:<user_id>`.
- Optional dev identity simulation (local only):
  - `Authorization: Bearer dev-user:<userId>`

### 4.3 Headers used by frontend clients
- `Authorization`: required unless `DEV_ALLOW_NO_AUTH=true` with `APP_PROFILE!=prod`.
- `X-Session-ID`: optional; if valid, server uses it.
- `X-Request-ID`: optional idempotency/correlation key for one request.
- `X-Run-ID`: optional alternative for trace/cancel routes.
- `X-User-ID`: **DEV-only** for local testing; in production the server must derive user identity from the bearer token. Client-provided user headers must be ignored in prod.

---

## 5. Global request constraints and normalization
- Max query length: `APP_MAX_QUERY_LEN` (default `8000`).
- Max length for most scalar fields: `APP_MAX_FIELD_LEN` (default `128`).
- `session_id` accepted pattern: `^[a-zA-Z0-9_-]+$`.
  - invalid value -> server generates a new session id.
- trace run id accepted pattern: `^[a-zA-Z0-9_.-]+$`.
  - invalid value -> ignored.

---

## 6. Startup contract: `GET /app-config`

### 6.1 Request
- Method: `GET`
- Path: `/app-config`
- Headers:
  - `Authorization` required (in no-auth mode it must be `Bearer dev-user:<user_id>`)
  - optional `X-Session-ID`

### 6.2 Response (200)
```json
{
  "repositories": ["nopCommerce"],
  "defaultRepository": "nopCommerce",
  "consultants": [
    {
      "id": "rejewski",
      "pipelineName": "rejewski",
      "snapshotPickerMode": "single",
      "snapshotSetId": "nopCommerce_4-60_4-90",
      "snapshots": [
        { "id": "48440Ahh", "label": "release-4.60.0" },
        { "id": "585959595", "label": "release-4.90.0" }
      ],
      "icon": "🧠",
      "displayName": "Marian Rejewski",
      "cardDescription": { "pl": "Analiza kodu", "en": "Code analysis" },
      "welcomeTemplate": { "pl": "Zapytaj {link}, ...", "en": "Ask {link}, ..." },
      "welcomeLinkText": { "pl": "Mariana Rejewskiego", "en": "Marian Rejewski" },
      "wikiUrl": { "pl": "...", "en": "..." }
    }
  ],
  "defaultConsultantId": "rejewski",
  "templates": { "consultants": [] },
  "translateChat": true,
  "isMultilingualProject": true,
  "neutralLanguage": "en",
  "translatedLanguage": "pl",
  "snapshotPolicy": "single",
  "historyGroups": [
    {
      "neutral_description": "today",
      "translated_description": "dzisiaj",
      "formula": { "type": "today" }
    },
    {
      "neutral_description": "last week",
      "translated_description": "ostatni tydzien",
      "formula": { "type": "last_n_days", "days": 7 }
    }
  ],
  "historyImportant": {
    "neutral_description": "important",
    "translated_description": "wazne",
    "show_important_on_the_top": true
  }
}
```

### 6.3 Semantics
- `consultants` are already filtered by user permissions.
- Localized consultant fields (`cardDescription`, `welcomeTemplate`, `welcomeLinkText`, `wikiUrl`) are maps keyed by language code.
  - Frontend should use current UI language key first, then fallback to another available key.
- `snapshotPickerMode` values:
  - `none`: no snapshot selector,
  - `single`: one selector,
  - `compare`: two selectors.
- `snapshotSetId` and `snapshots` are resolved server-side.
- `neutralLanguage` and `translatedLanguage` are normalized to short codes (`en`, `pl`, etc.).
- `isMultilingualProject=false` means UI should hide language selector and operate in neutral mode only.

### 6.4 Errors
- `401` unauthorized (`/prod` without valid bearer).
- `503` auth not configured in prod.
- `404` for `/dev` if dev mode disabled.

---

## 7. Query contract: `POST /search/{mode}` and `POST /query/{mode}`

Both routes are equivalent.

### 7.1 Canonical request body
```json
{
  "query": "Do czego sluzy encja Category.cs?",
  "consultant": "rejewski",
  "pipelineName": "rejewski",
  "translateChat": true,
  "enableTrace": true,
  "pipeline_run_id": "client_generated_run_id",
  "repository": "nopCommerce",
  "snapshot_set_id": "nopCommerce_4-60_4-90",
  "snapshots": ["48440Ahh", "585959595"]
}
```

### 7.2 Accepted aliases / additional fields
- query text: `query` (recommended), `question`, `text`
- trace flag: `enableTrace` or `enable_trace`
- run id: `pipeline_run_id` or `run_id`
- snapshot ids: `snapshot_id`, `snapshotId`, `snapshot_id_b`, `snapshotIdB`
- snapshot set: `snapshot_set_id` or `snapshotSetId`
- branch compare: `branches` or `branchA` + `branchB` (or single `branch`)
- optional: `source_system_id`, `user_id`, `session_id`

### 7.3 Snapshot and compare rules
- `snapshots` may contain 0..2 values.
- if 2 values are provided, they must be different.
- if `snapshot_set_id` is present, each selected snapshot must belong to this set.
- if pipeline has fixed snapshot set in YAML, request set must match it.

### 7.4 Response (200, success)
```json
{
  "ok": true,
  "session_id": "747fc839b80046f288dfd8e1c697e8cb",
  "consultant": "rejewski",
  "pipelineName": "rejewski",
  "repository": "nopCommerce",
  "trace_enabled": true,
  "pipeline_run_id": "1771704709712_...",
  "results": "<markdown>",
  "query_type": "DIRECT",
  "steps_used": 9,
  "translated": "<diagnostic text>",
  "branches": ["A", "B"],
  "branchA": "A",
  "branchB": "B"
}
```

### 7.5 Cancellation response from query route
If run is cancelled while executing, query route can return:
```json
{
  "ok": false,
  "cancelled": true,
  "error": "cancelled",
  "pipeline_run_id": "..."
}
```
HTTP status is still `200`.

### 7.6 Error responses
- `400`: invalid payload (missing required field, too many snapshots/branches, mismatch).
- `401`: unauthorized on prod route.
- `403`: pipeline not allowed for user.
- `500`: unhandled server/runtime error.

---

## 8. Trace stream contract

### 8.1 Open SSE stream
- `GET /pipeline/stream/{mode}?run_id=<pipeline_run_id>`
- `run_id` can also be sent in `X-Run-ID`.
- Content type: `text/event-stream`.

### 8.2 Events emitted
Server sends JSON lines as `data: <json>`.

Done event:
```json
{ "type": "done", "reason": "done" }
```
or
```json
{ "type": "done", "reason": "cancelled" }
```

Step event shape:
```json
{
  "type": "step",
  "ts": "2026-02-22T10:12:13Z",
  "run_id": "...",
  "step_id": "fetch_node_texts",
  "action_id": "fetch_node_texts",
  "summary": "Context materialization",
  "summary_translated": "Budowanie kontekstu",
  "caption": "Materializing context",
  "caption_translated": "Budowanie kontekstu",
  "details": {
    "node_texts_count": 8
  },
  "docs": [
    {
      "id": "doc:123",
      "depth": 1,
      "text_len": 420,
      "preview": "...",
      "markdown": "..."
    }
  ]
}
```

Other event types can appear (`enqueue`, `consume`) depending on callback policy.

### 8.3 Keep-alive
Server may emit comment keep-alive lines:
```text
: keep-alive
```

### 8.4 Cancel endpoint
- `POST /pipeline/cancel/{mode}`
- body:
```json
{ "pipeline_run_id": "..." }
```
(also accepts `run_id`)

Response:
```json
{ "ok": true, "run_id": "...", "cancelled": true }
```

---

## 9. Chat history API contract

### 9.1 Availability
History endpoints are available only when mock SQL history is enabled:
- `config.json: mockSqlServer=true`
- and development mode enabled

Otherwise all history endpoints return `503` with:
```json
{
  "error": "history_persistence_unavailable",
  "message": "History persistence is not available. Enable development mode and mockSqlServer in config."
}
```

### 9.2 User resolution for history
- With `Authorization: Bearer dev-user:<id>` -> that user id.
- Without it -> `anon`.

Behavior for `anon`:
- list sessions: empty,
- get messages: empty,
- create session/message: accepted response but not persisted,
- session get/patch/delete: not found.

### 9.3 Sessions list
`GET /chat-history/sessions?limit=<1..200>&cursor=<updatedAt>&q=<title_substring>`

Response:
```json
{
  "items": [
    {
      "sessionId": "s_123",
      "tenantId": "tenant-default",
      "userId": "dev-user-1",
      "title": "Category in Nop",
      "consultantId": "rejewski",
      "createdAt": 1719140000000,
      "updatedAt": 1719140300000,
      "messageCount": 6,
      "important": true,
      "status": "active",
      "deletedAt": null,
      "softDeletedAt": null
    }
  ],
  "next_cursor": "1719140300000"
}
```

Rules:
- sorted by `updatedAt` descending,
- excludes `deletedAt` and `softDeletedAt` sessions,
- `q` searches in `title` (case-insensitive),
- `next_cursor` is last returned `updatedAt` when page is full.

### 9.4 Create session
`POST /chat-history/sessions`

Accepted body fields:
- `sessionId` or `session_id` (optional)
- `title` or `firstQuestion` (optional)
- `consultantId` or `consultant` (optional)

Response returns created session object.

### 9.5 Session details and updates
- `GET /chat-history/sessions/{sessionId}`
- `PATCH /chat-history/sessions/{sessionId}`
- `DELETE /chat-history/sessions/{sessionId}`

PATCH body fields:
- `title`
- `consultantId`
- `important` (boolean)
- `softDeleted` (boolean)

DELETE behavior:
- soft-delete only (`softDeletedAt` + `status=soft_deleted`).
- Soft-deleted sessions are hidden from session list and should be treated by frontend as no longer accessible.

### 9.6 Messages API
- `GET /chat-history/sessions/{sessionId}/messages?limit=<1..200>&before=<ts_ms>`
- `POST /chat-history/sessions/{sessionId}/messages`

POST body:
- `messageId` or `message_id` (optional)
- `q` (string)
- `a` (string)
- `meta` (object, optional)

Messages response shape:
```json
{
  "items": [
    {
      "messageId": "m_1",
      "sessionId": "s_123",
      "ts": 1719140000000,
      "q": "...",
      "a": "...",
      "meta": null,
      "deletedAt": null
    }
  ],
  "next_cursor": "1719140000000"
}
```

Pagination:
- returns newest window constrained by `limit`,
- with `before`, returns messages with `ts < before`,
- `next_cursor` equals first returned `ts` when page is full.

---

## 10. Optional auth probe endpoint

- `GET /auth-check`
- When bearer auth is required, it validates the bearer token.
- Success:
```json
{ "ok": true, "profile": "prod", "auth": "bearer" }
```
- Errors: same auth errors as other protected endpoints (`401`, `503`).

---

## 11. UI behavior rules required by contract

### 11.1 Consultant and pipeline selection
- UI displays consultants from `app-config.consultants`.
- Query request must include `consultant`.
- `pipelineName` may also be sent; if omitted server resolves from templates.

### 11.2 Snapshot controls
- mode `none`: hide selectors, send `snapshots: []`.
- mode `single`: send one snapshot id.
- mode `compare`: send exactly two different ids.

### 11.3 Snapshot policy
`app-config.snapshotPolicy`:
- `single`: switching consultant to another snapshot set should start a new chat.
- `multi_confirm`: switch allowed after explicit confirmation.
- `multi_silent`: switch allowed without confirmation.

### 11.4 Multilingual toggle
- If `isMultilingualProject=true`:
  - show language selector,
  - offer `translatedLanguage` and `neutralLanguage`,
  - set `translateChat=true` only when selected language equals `translatedLanguage`.
- If `isMultilingualProject=false`:
  - hide language selector,
  - force neutral language UI behavior,
  - always send `translateChat=false`.

### 11.5 Session continuity
- Reuse `session_id` for subsequent turns in same chat.
- Accept server-generated `session_id` and store it client-side.

### 11.6 Rendering
- Render `results` as markdown.
- Trace panel should attach to `pipeline_run_id` when `trace_enabled=true`.

### 11.7 History interactions
- Rename -> `PATCH { title }`
- Mark/unmark important -> `PATCH { important }`
- Delete one chat -> `DELETE /sessions/{id}` (soft delete)
- Clear all -> iterate sessions and send `PATCH { softDeleted: true }`

---

## 12. Mock server parity requirements
`frontend/mock/server.js` should mirror this contract for local frontend work:
- app-config structure,
- search/query response shape,
- trace stream done/step events,
- cancel response,
- chat-history endpoints and pagination fields.

Goal: frontend can switch from mock to Python backend without protocol changes.

---

## 13. Contract evolution rules
- Additive changes are preferred.
- Do not remove or rename existing fields without a versioned migration plan.
- If new frontend behavior requires server fields, document them here first.
