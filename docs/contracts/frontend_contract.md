# Frontend contract: consultants, pipelines, snapshots, `ui_contracts` (EN)

## Scope
This document specifies the backend↔frontend contract for:
- dynamic loading of “consultants” (UI cards),
- consultant → pipeline mapping,
- UI visibility control for snapshot selection,
- trace panel stream + cancel behavior,
- a shared contract for Python backend and a JS mock server.

It is framework-agnostic so a team can build the UI in Angular (or any other framework) without reading backend code.

---

## Repository layout (agreed)
```
ui_contracts/
  frontend_requirements/
    base_frontend_requirements.json
    templates.json
```

### `base_frontend_requirements.json`
Base contract: shared fields, contract version, minimum frontend expectations.

Recommended fields:
- `contractVersion` (e.g., `"1.0"`)
- JSON schema notes (as descriptive fields / comments)
- optional defaults (if needed)

### `templates.json`
Single source of truth for consultant UI templates.

Each template:
- defines the consultant card visuals and texts,
- references `pipelineName`,
- defines the snapshot UI mode (`snapshotPickerMode`).

---

## Glossary (UI vs backend naming)
- **Pipeline**: backend execution unit (YAML). Permissions are assigned to pipelines.
- **Consultant**: UI presentation of a pipeline (card, texts, icon). Currently 1:1 with a pipeline.
- **SnapshotSet** (backend) ↔ **Project** (UX label)
- **Snapshot** (backend) ↔ **Version** (UX label)

UI should show “Project / Version”, but must send `snapshot_set_id` and `snapshot_id` to the backend.

---

## Template → pipeline mapping
In `templates.json`, `pipelineName` selects which pipeline to execute after choosing a consultant.

Example:
```json
{
  "id": "shannon",
  "pipelineName": "shannon"
}
```

Frontend does not know YAML details; it only sends the pipeline name.
Current assumption: `consultant.id` equals `pipelineName` (1:1 mapping). If this changes, the backend must expose a distinct `pipelineName` and the frontend must send it explicitly.

---

## UI control: `snapshotPickerMode`
Minimal UI control mechanism for snapshot selection.

Values:
- `none` — show no version selectors (assume no retrieval)
- `single` — show 1 version selector
- `compare` — show 2 version selectors + “vs” separator
If the value is missing/unknown, the frontend should treat it as `single`.

Templates must include `snapshotPickerMode`.

Examples:
```json
{
  "id": "rejewski",
  "pipelineName": "rejewski",
  "snapshotPickerMode": "single"
}
```

```json
{
  "id": "shannon",
  "pipelineName": "shannon",
  "snapshotPickerMode": "compare"
}
```

```json
{
  "id": "ada",
  "pipelineName": "ada",
  "snapshotPickerMode": "none"
}
```

---

## Backend → frontend startup contract: `GET /app-config*`
Frontend bootstraps via:
- `GET /app-config/dev` in development mode
- `GET /app-config/prod` in production mode

Compatibility:
- There is no legacy `/app-config` alias in strict mode.
- Use explicit mode endpoints only: `/app-config/dev` or `/app-config/prod`.

Minimum response fields:
- `contractVersion`
- `defaultConsultantId`
- `consultants[]` — consultant templates filtered by permissions
- `snapshotPolicy` — how to confirm snapshot set changes

Each consultant includes:
- `pipelineName`
- `snapshotSetId` (empty if no retrieval)
- `snapshots[]` (empty if no retrieval)
  - each snapshot has `id` and `label`
Additional consultant fields:
- `cardDescription`, `welcomeTemplate`, `welcomeLinkText`, `wikiUrl` are localized objects: `{ "pl": "...", "en": "..." }`.
  - If a key is missing for the current UI language, the frontend should fall back to another language (e.g., `en`) or the first available value.
- `icon` is a plain text string (emoji recommended). The UI treats it as text.

Logical structure:
```json
{
  "contractVersion": "1.0",
  "defaultConsultantId": "rejewski",
  "snapshotPolicy": "single",
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
  ]
}
```

Notes:
- `snapshots[].label` is what UI should display as “Version”.
- `snapshots[].id` is what UI sends in `snapshots[]`.
  Backend mapping:
  - first item → `snapshot_id` (primary)
  - second item (if present) → `snapshot_id_b` (secondary)
- When `snapshotPickerMode` is `none`, both `snapshotSetId` and `snapshots[]` are empty.
`snapshotPolicy` values:
- `single` — if snapshot set changes, require starting a new chat.
- `multi_confirm` — allow switching with confirmation and log a system message.
- `multi_silent` — allow switching without confirmation.

---

## Frontend: request payload (`POST /search*`)
Frontend sends:
- `pipelineName` (or `consultant`) from the selected consultant
- `snapshot_set_id` from consultant (if present)
- `snapshots[]` as a list of 0..2 snapshot IDs
- `X-Session-ID` (if present; otherwise backend generates and returns it)

Rules for `snapshots[]`:
- missing or empty list = no retrieval
- 1 item = single version
- 2 items = compare mode; items must be different
For compare mode, the frontend must disable “Send” until 2 different snapshot IDs are selected.

Backend validation rule:
- when `snapshot_set_id` is present, both selected snapshots (primary + optional secondary) must belong to that set.

Logical payload (no retrieval / `snapshotPickerMode: none`):
```json
{
  "query": "...",
  "consultant": "ada",
  "translateChat": true,
  "snapshots": []
}
```

Logical payload (single version):
```json
{
  "query": "...",
  "consultant": "rejewski",
  "snapshot_set_id": "nopCommerce_4-60_4-90",
  "snapshots": ["48440Ahh"],
  "translateChat": true
}
```

Logical payload (compare):
```json
{
  "query": "...",
  "consultant": "shannon",
  "snapshot_set_id": "fakeSnapSet",
  "snapshots": ["aaa111", "bbb222"],
  "translateChat": true
}
```

Notes:
- The current UI sends `consultant` (not `pipelineName`) and it is expected to be the consultant `id`.
- `translateChat: true` means the UI language is Polish; `false` means English. Backend may use it to control prompts or translation behavior.

---

## UX rules (framework-agnostic)
- Show **Project** and **Version** in the UI, but send `snapshot_set_id` and `snapshot_id`.
- Hide the version selectors when `snapshotPickerMode` is `none` or `snapshots[]` is empty.
- In compare mode, require two different versions before enabling “Send”.
- One chat must not mix different `snapshot_set_id` values.
  - If the user switches to a consultant with a different `snapshotSetId` and the conversation already used a non-empty set, show a confirmation and start a new chat if accepted.
- Trace filter highlight is visual-only; it does not change the contract or request payloads.

Endpoint selection:
- development: `POST /search/dev`
- production: `POST /search/prod`

When development endpoints are disabled (`developement=false`), `/dev` endpoints return `404`.

## Response contract (`POST /search*`)
Minimum response fields:
- `results` — markdown string; frontend renders it as markdown
- `session_id` — may be returned on every response or only once; frontend should update session id if present

Optional fields:
- `pipeline_run_id` — identifier used to attach trace stream and to cancel the request.
- `cancelled: true` — when the backend acknowledges cancellation; `results` may be empty.

If the backend returns `cancelled: true`, frontend should:
- keep the last user question in the conversation,
- show a "Cancelled" status in trace panel.

---

## Chat history API contract

Frontend uses a dedicated history API for listing sessions and loading messages.

Endpoints:
- `GET /chat-history/sessions?limit=50&cursor=...&q=...`
- `GET /chat-history/sessions/{sessionId}`
- `GET /chat-history/sessions/{sessionId}/messages?limit=100&before=...`
- `POST /chat-history/sessions`
- `POST /chat-history/sessions/{sessionId}/messages`
- `PATCH /chat-history/sessions/{sessionId}`
- `DELETE /chat-history/sessions/{sessionId}`

Session list response shape:
```json
{
  "items": [
    {
      "sessionId": "s_123",
      "title": "Pytanie o UML",
      "consultantId": "ada",
      "createdAt": 1719140000000,
      "updatedAt": 1719140300000,
      "messageCount": 6
    }
  ],
  "next_cursor": "1719140000000"
}
```

Messages response shape:
```json
{
  "items": [
    {
      "messageId": "m_1",
      "ts": 1719140000000,
      "q": "Zrób diagram klas",
      "a": "..."
    }
  ],
  "next_cursor": "1719140000000"
}
```

If history persistence is unavailable, the UI shows:
`Brak uruchomionego serwera persystencji historii (chat-history).`

---

## Trace stream + cancel contract

### Trace stream endpoint
Frontend opens a Server-Sent Events stream:
- development: `GET /pipeline/stream/dev?run_id=<pipeline_run_id>`
- production: `GET /pipeline/stream/prod?run_id=<pipeline_run_id>`

Stream emits:
- `type: "step"` events (see UI trace panel)
- `type: "done"` when the run finishes
- `type: "done", reason: "cancelled"` when the run is cancelled

### Stage visibility policy (config + pipeline)
Stage visibility is controlled server-side and affects which events are sent to the UI.

Global (`config.json`):
- `stages_visibility: "allowed" | "forbidden" | "explicit" | "pipeline_driven"`

Pipeline (`pipeline.settings` in YAML):
- `stages_visibility: "allowed" | "forbidden" | "explicit"`

Precedence:
- Global config wins, unless `stages_visibility: "pipeline_driven"`.
- In `explicit` mode, a step must declare `stages_visible: true` to be emitted.

Note:
- `captioned` filtering was removed. There is no caption-based filtering anymore.

### Cancel endpoint
Frontend can cancel an in-flight query:
- development: `POST /pipeline/cancel/dev`
- production: `POST /pipeline/cancel/prod`

Payload:
```json
{ "pipeline_run_id": "<id>" }
```

Backend should:
- mark the run as cancelled,
- close the trace stream with `reason: "cancelled"`,
- return `{ ok: true, cancelled: true }`.

Frontend behavior:
- the single "Send" button toggles to cancel state during an in-flight request,
- clicking it sends the cancel request and aborts the client fetch,
- trace panel should show a "Cancelled" status.

---

## Backend: building `/app-config*`
Minimal flow:
1. Identify user
2. Create session
3. Resolve allowed pipelines for the user
4. Select templates (from `templates.json`) only for allowed pipelines
5. For each pipeline, resolve `snapshot_set_id` from YAML
6. Resolve `snapshots[]` from Weaviate (labels + ids)
7. Return `/app-config/dev` or `/app-config/prod` depending on mode

---

## JS mock server
The mock server should expose `/app-config/dev` and `/search/dev` as canonical development endpoints.
It should also expose `/pipeline/stream/dev` and `/pipeline/cancel/dev` to keep UI behavior consistent.
Goal: allow testing UI without Python, then switch to Python backend without UI changes.

---

## Out of scope (this sprint)
- fine-grained UI permissions for special buttons (e.g. “Save to EA”)
- for now such special features are returned as links in the response only for authorized users
