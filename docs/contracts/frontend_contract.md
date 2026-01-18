# Frontend contract: consultants, pipelines, `ui_contracts` (EN)

## Scope
This document specifies the backend↔frontend contract for:
- dynamic loading of “consultants” (UI cards),
- consultant → pipeline mapping,
- UI visibility control (currently: branch picker mode),
- a shared contract for Python backend and a JS mock server.

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
- defines the branch UI mode (`branchPickerMode`).

---

## Definitions

### Pipeline
Backend execution unit (YAML).  
Permissions are assigned to pipelines (security/functionality), not to templates.

### UI template
Frontend presentation configuration for a consultant.  
A template is a “view” on top of a pipeline, not logic.

---

## Template → pipeline mapping
In `templates.json`, `pipelineName` selects which pipeline to execute after choosing a consultant.

Example:
```json
{
  "id": "shannon",
  "pipelineName": "branch_compare_base"
}
```

Frontend does not know YAML details; it only sends the pipeline name.

---

## UI control: `branchPickerMode`
Minimal UI control mechanism for branch selection.

Values:
- `none` — show no branch selects (assume no retrieval or retrieval not needed)
- `single` — show 1 branch select
- `compare` — show 2 branch selects + “vs” separator

Templates must include `branchPickerMode`.

Examples:
```json
{
  "id": "rejewski",
  "pipelineName": "marian_rejewski_code_analysis_base",
  "branchPickerMode": "single"
}
```

```json
{
  "id": "shannon",
  "pipelineName": "branch_compare_base",
  "branchPickerMode": "compare"
}
```

```json
{
  "id": "direct",
  "pipelineName": "direct_answer_base",
  "branchPickerMode": "none"
}
```

---

## Backend → frontend startup contract: `/app-config`
Frontend bootstraps via `GET /app-config`.

Minimum response fields:
- `contractVersion`
- `defaultConsultantId`
- `branches[]` — list of available branches (currently from indexes)
- `consultants[]` — consultant templates filtered by permissions

Logical structure:
```json
{
  "contractVersion": "1.0",
  "defaultConsultantId": "rejewski",
  "branches": ["2025-12-14__develop", "2025-12-14__release_4_60"],
  "consultants": [
    {
      "id": "rejewski",
      "pipelineName": "marian_rejewski_code_analysis_base",
      "branchPickerMode": "single",
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

Note:
- The legacy `/branch` endpoint is replaced by `branches[]` in `/app-config`.

---

## Frontend: request payload
Frontend sends:
- `pipelineName` from the selected consultant,
- `branches` as a list of 0..2 items,
- `X-Session-ID` (if present; otherwise backend generates and returns it).

Rules for `branches`:
- missing or empty list = no branch selected (assume no retrieval)
- 1 item = single branch
- 2 items = compare mode; branches must be different

Logical payload (no retrieval / `branchPickerMode: none`):
```json
{
  "query": "...",
  "pipelineName": "direct_answer_base",
  "translateChat": true
}
```

Logical payload (single branch):
```json
{
  "query": "...",
  "pipelineName": "marian_rejewski_code_analysis_base",
  "branches": ["2025-12-14__release_4_90"],
  "translateChat": true
}
```

Logical payload (compare):
```json
{
  "query": "...",
  "pipelineName": "branch_compare_base",
  "branches": ["2025-12-14__release_4_90", "2025-12-14__release_4_60"],
  "translateChat": true
}
```

---

## Backend: building `/app-config`
Minimal flow:
1. Identify user (currently: `anonymous`)
2. Create session
3. Resolve allowed pipelines for the user
4. Select templates (from `templates.json`) only for allowed pipelines
5. Resolve available branches (currently from indexes)
6. Return `/app-config`

---

## JS mock server
The mock server must expose `/app-config` compatible with this contract.  
Goal: allow testing UI without Python, then switch to Python backend without UI changes.

---

## Out of scope (this sprint)
- fine-grained UI permissions for special buttons (e.g. “Save to EA”)
- for now such special features are returned as links in the response only for authorized users
