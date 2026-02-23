# Weaviate CLI (import + snapshot browsing + SnapshotSets)

This document describes the **CLI tools** used to:
- **import** repository bundles (snapshots) into Weaviate
- **discover** which snapshots exist (and their `snapshot_id`)
- **manage SnapshotSets** (named allowlists / query scopes)

Weaviate must already be running (see `docs/weaviate/weaviate_local_setup.md`).

---

## 1) Snapshot identity model (IMPORTANT)

### 1.1 `snapshot_id` is the only identifier

- `snapshot_id` is the **real snapshot identifier** used everywhere (CLI, backend, frontend).
- `snapshot_id` is also the **Weaviate tenant id** (multi-tenancy partition key).

`head_sha` is **informational only** (useful for humans / debugging), and must **never** be used as an identifier in requests.

### 1.2 How `snapshot_id` is computed

Snapshots are identified deterministically from repository metadata:

- If `HeadSha` is present:
  - `snapshot_id = UUID5("{RepoName}:{HeadSha}")`
- If `HeadSha` is empty/missing:
  - `snapshot_id = UUID5("{RepoName}:{FolderFingerprint}")`

Example metadata (`repo_meta.json`):

```json
{
  "RepoName": "NopCommerce",
  "Branch": "release-4.90.0",
  "HeadSha": "e7a52b9199f9c7651839e92826df47f668f3c767",
  "RepositoryRoot": "D:/TrainingCode/Nop/nopCommerce",
  "FolderFingerprint": null,
  "GeneratedAtUtc": "2026-02-08T16:48:45.3981022Z"
}
```

---

## 2) Connection and auth model

### 2.1 Resolution order (highest → lowest priority)

Connection settings are resolved in this order:

1) CLI flags (if provided)  
2) Environment variables (e.g., `WEAVIATE_API_KEY`)  
3) `config.json` (`weaviate.host/http_port/grpc_port/ready_timeout_seconds`)  
4) Defaults (`localhost / 18080 / 15005`)  

### 2.2 `.env` loading (`--env`)

`.env` is **not** loaded automatically by your shell.

All CLI tools support:

- `--env`  
  Loads `<repo_root>/.env` for the current process **without overriding** already-set environment variables.

Use `--env` when:
- your API key is stored in `.env` as `WEAVIATE_API_KEY=...`
- you run the CLI from a clean shell / terminal

### 2.3 Quiet by default (`--verbose`)

The CLIs are **quiet by default** (no httpx request spam).

- Default: only tool output (OK / errors / tables)
- `--verbose`: enable extra diagnostic output (including client HTTP logs)

Examples:
```bash
python -m tools.weaviate.snapshot_sets --env --verbose list
python -m tools.weaviate.import_branch_to_weaviate --env --verbose ...
```

---

## 3) Import a snapshot bundle into Weaviate

Module:
```
tools/weaviate/import_branch_to_weaviate.py
```

### 3.1 Import a branch snapshot (.zip)

```bash
python -m tools.weaviate.import_branch_to_weaviate --env   --bundle repositories/nopCommerce/branches/release-4.60.0.zip   --embed-model models/embedding/e5-base-v2   --ref-type branch   --ref-name release-4.60.0
```

```bash
python -m tools.weaviate.import_branch_to_weaviate --env   --bundle repositories/nopCommerce/branches/release-4.90.0.zip   --embed-model models/embedding/e5-base-v2   --ref-type branch   --ref-name release-4.90.0
```

### 3.2 Important: bundle format

`--bundle` must point to:
- a **folder** containing `repo_meta.json`, or
- a **.zip** containing `repo_meta.json` at the root of the archive

If you see:
- `repo_meta.json not found in folder`
- `There is no item named 'repo_meta.json' in the archive`

…it means the path or zip layout is wrong.

### 3.3 Importer flags (high-level)

Required:
- `--bundle` : bundle folder or `.zip`
- `--embed-model` : SentenceTransformer model path/name

Recommended:
- `--env` : load `.env` from repo root

Optional overrides:
- `--weaviate-host`, `--weaviate-http-port`, `--weaviate-grpc-port`
- `--weaviate-api-key` (prefer `WEAVIATE_API_KEY` in `.env` instead)

---

## 4) Discover available snapshots (what is in Weaviate)

Imports are recorded in the `ImportRun` collection.

Each import corresponds to one `snapshot_id` (tenant id). `head_sha` is recorded as **informational metadata**.

### 4.1 CLI way (recommended): list snapshots

```bash
python -m tools.weaviate.snapshot_sets --env snapshots
```

Optional repo filter:

```bash
python -m tools.weaviate.snapshot_sets --env snapshots --repo nopCommerce
```

What you’ll see (conceptually):
- `repo`
- `ref_type` + `ref_name` (the label you imported under)
- `tag` / `branch` (if present)
- `snapshot_id` (the real id / tenant id)
- `head_sha` (informational only)
- timestamps / status

### 4.2 Raw GraphQL way (optional)

Resolve `snapshot_id` by tag:

```bash
TAG="release-4.60.0"

curl -s http://localhost:18080/v1/graphql   -H 'Content-Type: application/json'   -d @- <<JSON | python -m json.tool
{
  "query": "{ Get { ImportRun(where:{path:[\"tag\"],operator:Equal,valueText:\"${TAG}\"}, limit:5){ repo ref_type ref_name branch tag snapshot_id head_sha status started_utc finished_utc } } }"
}
JSON
```

Resolve `snapshot_id` by branch:

```bash
BRANCH="release-4.90.0"

curl -s http://localhost:18080/v1/graphql   -H 'Content-Type: application/json'   -d @- <<JSON | python -m json.tool
{
  "query": "{ Get { ImportRun(where:{path:[\"branch\"],operator:Equal,valueText:\"${BRANCH}\"}, limit:5){ repo ref_type ref_name branch tag snapshot_id head_sha status started_utc finished_utc } } }"
}
JSON
```

---

## 5) SnapshotSets (query scopes)

A **SnapshotSet** is a named **allowlist of `snapshot_id`** values.

- Frontend sends: `snapshot_set_id` + `snapshots: [snapshot_id, ...]`
- Backend validates: each requested `snapshot_id` belongs to the given `snapshot_set_id`
- Weaviate access is tenant-scoped by `snapshot_id` (multi-tenancy)

Module:
```
tools/weaviate/snapshot_sets.py
```

Commands (high level):
- `snapshots` — list imported snapshots (from `ImportRun`) and optionally **build** a SnapshotSet from selected items
- `list`      — list SnapshotSets
- `show`      — show one SnapshotSet
- `add`       — create/update a SnapshotSet (explicit mode)
- `delete`    — delete a SnapshotSet
- `purge-snapshot` — delete a snapshot's data + remove it from SnapshotSets (interactive)

### 5.1 List SnapshotSets

```bash
python -m tools.weaviate.snapshot_sets --env list
```

Filter by repo:

```bash
python -m tools.weaviate.snapshot_sets --env list --repo nopCommerce
```

### 5.2 Show a SnapshotSet

```bash
python -m tools.weaviate.snapshot_sets --env show --id nopCommerce_4-60_4-90
```

### 5.3 Create a SnapshotSet from listed snapshots (interactive)

Start the snapshot browser:

```bash
python -m tools.weaviate.snapshot_sets --env snapshots
```

Then type:
- `1,2` to select items 1 and 2 and create a SnapshotSet
- the tool proposes an ID (you can accept or change it)

### 5.4 Add / update a SnapshotSet (explicit mode)

Example (two snapshot labels; resolved via `ImportRun` → `snapshot_id`):

```bash
python -m tools.weaviate.snapshot_sets --env add   --id nopCommerce_4-60_4-90   --repo nopCommerce   --snapshots release-4.60.0 release-4.90.0   --description "Public subset: 4.60 + 4.90"
```

Example (explicit snapshot ids):

```bash
python -m tools.weaviate.snapshot_sets --env add   --id nopCommerce_4-60_4-90   --repo nopCommerce   --snapshot-ids 0317701f-8103-5146-bbe9-4cedd73365f4 5fcda9c6-e491-5807-b18b-9eb037b0287a
```

Mark as inactive:

```bash
python -m tools.weaviate.snapshot_sets --env add   --id nopCommerce_4-60_4-90   --repo nopCommerce   --snapshots release-4.60.0 release-4.90.0   --inactive
```

### 5.5 Delete a SnapshotSet

```bash
python -m tools.weaviate.snapshot_sets --env delete --id nopCommerce_4-60_4-90
```

Optional safety check:

```bash
python -m tools.weaviate.snapshot_sets --env delete   --id nopCommerce_4-60_4-90   --repo nopCommerce
```

### 5.6 Purge a snapshot (data + SnapshotSets)

Deletes:
- `RagNode` + `RagEdge` data for the snapshot (tenant = `snapshot_id`)
- `ImportRun` metadata rows for the snapshot
- Removes the snapshot from all SnapshotSets
- If a SnapshotSet becomes empty, it is **deleted**

Interactive (recommended):

```bash
python -m tools.weaviate.snapshot_sets --env purge-snapshot
```

With repo filter:

```bash
python -m tools.weaviate.snapshot_sets --env purge-snapshot --repo nopCommerce
```

Non-interactive:

```bash
python -m tools.weaviate.snapshot_sets --env purge-snapshot --select 3 --yes
```

---

## 6) Common CLI failures

### `401 Unauthorized`
Weaviate has API key auth enabled but your CLI did not send a key.

Fix:
- Put the key into `.env` as `WEAVIATE_API_KEY=...`
- Run the tool with `--env`, or export the variable in your shell.

### `.env` was loaded but API key is still empty
Ensure `.env` contains:
```env
WEAVIATE_API_KEY=your-real-key-here
```

And that you are running with `--env`.

### `Connection refused`
Weaviate is not running, or ports mismatch.

```bash
docker ps | grep weaviate || true
curl -sS http://localhost:18080/v1/meta | head
ss -ltnp | egrep '(:18080|:15005)\b' || true
```
