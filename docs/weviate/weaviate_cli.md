# Weaviate CLI (import + snapshot browsing + SnapshotSets)

This document describes the **CLI tools** used to:
- **import** repository bundles (snapshots) into Weaviate
- **discover** which snapshots exist (and their `head_sha`)
- **manage SnapshotSets** (named allowlists / query scopes)

Weaviate must already be running (see `weaviate_local_setup.md`).

---

## 1) Connection and auth model

### 1.1 Resolution order (highest → lowest priority)

Connection settings are resolved in this order:

1) CLI flags (if provided)  
2) Environment variables (e.g., `WEAVIATE_API_KEY`)  
3) `config.json` (`weaviate.host/http_port/grpc_port/ready_timeout_seconds`)  
4) Defaults (`localhost / 18080 / 15005`)  

### 1.2 `.env` loading (`--env`)

`.env` is **not** loaded automatically by your shell.

All CLI tools support:

- `--env`  
  Loads `<repo_root>/.env` for the current process **without overriding** already-set environment variables.

Use `--env` when:
- your API key is stored in `.env` as `WEAVIATE_API_KEY=...`
- you run the CLI from a clean shell / terminal

### 1.3 Quiet by default (`--verbose`)

The CLIs are **quiet by default** (no httpx request spam).

- Default: only tool output (OK / errors / tables)
- `--verbose`: enable extra diagnostic output (including client HTTP logs)

Examples:
```bash
python -m tools.weaviate.snapshot_sets --env --verbose list
python -m tools.weaviate.import_branch_to_weaviate --env --verbose ...
```

---

## 2) Import a snapshot bundle into Weaviate

Module:
```
tools/weaviate/import_branch_to_weaviate.py
```

### 2.1 Import a tag snapshot (.zip)

```bash
python -m tools.weaviate.import_branch_to_weaviate --env \
  --bundle repositories/nopCommerce/branches/release-4.60.0.zip \
  --embed-model models/embedding/e5-base-v2 \
  --ref-type tag \
  --ref-name release-4.60.0 \
  --tag release-4.60.0
```

### 2.2 Import a branch snapshot (.zip)

```bash
python -m tools.weaviate.import_branch_to_weaviate --env \
  --bundle repositories/nopCommerce/branches/release-4.90.0.zip \
  --embed-model models/embedding/e5-base-v2 \
  --ref-type branch \
  --ref-name release-4.90.0
```

### 2.3 Important: bundle format

`--bundle` must point to:
- a **folder** containing `repo_meta.json`, or
- a **.zip** containing `repo_meta.json` at the root of the archive

If you see:
- `repo_meta.json not found in folder`
- `There is no item named 'repo_meta.json' in the archive`

…it means the path or zip layout is wrong.

### 2.4 Importer flags (high-level)

Required:
- `--bundle` : bundle folder or `.zip`
- `--embed-model` : SentenceTransformer model path/name

Recommended:
- `--env` : load `.env` from repo root

Optional overrides:
- `--weaviate-host`, `--weaviate-http-port`, `--weaviate-grpc-port`
- `--weaviate-api-key` (prefer `WEAVIATE_API_KEY` in `.env` instead)

---

## 3) Discover available snapshots (what is in Weaviate)

Imports are recorded in the `ImportRun` collection. Each import corresponds to one immutable `head_sha`.

### 3.1 CLI way (recommended): list snapshots

This is the “what can I build a SnapshotSet from?” command.

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
- `head_sha`
- timestamps / status

### 3.2 Raw GraphQL way (optional)

Resolve `head_sha` by tag:

```bash
TAG="release-4.60.0"

curl -s http://localhost:18080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d @- <<JSON | python -m json.tool
{
  "query": "{ Get { ImportRun(where:{path:[\"tag\"],operator:Equal,valueText:\"${TAG}\"}, limit:5){ repo branch tag head_sha friendly_name status } } }"
}
JSON
```

Resolve `head_sha` by branch:

```bash
BRANCH="release-4.90.0"

curl -s http://localhost:18080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d @- <<JSON | python -m json.tool
{
  "query": "{ Get { ImportRun(where:{path:[\"branch\"],operator:Equal,valueText:\"${BRANCH}\"}, limit:5){ repo branch tag head_sha status } } }"
}
JSON
```

---

## 4) SnapshotSets (query scopes)

A **SnapshotSet** is a named **allowlist** of snapshots that can be queried.
It later becomes a filter on `RagNode` / `RagEdge` by `head_sha`.

Module:
```
tools/weaviate/snapshot_sets.py
```

Commands:
- `snapshots` — list imported snapshots (from `ImportRun`) and optionally **build** a SnapshotSet from selected items
- `list`      — list SnapshotSets
- `show`      — show one SnapshotSet
- `add`       — create/update a SnapshotSet (explicit mode)
- `delete`    — delete a SnapshotSet
- `purge-snapshot` — delete a snapshot's data + remove it from SnapshotSets (interactive)

### 4.1 List SnapshotSets

```bash
python -m tools.weaviate.snapshot_sets --env list
```

Filter by repo:

```bash
python -m tools.weaviate.snapshot_sets --env list --repo nopCommerce
```

JSON output:

```bash
python -m tools.weaviate.snapshot_sets --env list --format json
```

**Tip:** In `list` output, the SnapshotSet **ID** is the second token after the repo name, e.g.
```
- nopCommerce / nopCommerce_release-4-60-0_release-4-90-0  active=True  refs=2  shas=2
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
             SnapshotSet ID
```

### 4.2 Show a SnapshotSet

```bash
python -m tools.weaviate.snapshot_sets --env show --id nopCommerce_release-4-60-0_release-4-90-0
```

### 4.3 Create a SnapshotSet from listed snapshots (interactive)

Start the snapshot browser (it prints numbered entries and then asks for selection):

```bash
python -m tools.weaviate.snapshot_sets --env snapshots
```

Then type:
- `1,2` to select items 1 and 2 and create a SnapshotSet
- the tool proposes an ID (you can accept or change it)

Note: the list shows `friendly_name` when available (fallback to tag/branch/ref).

### 4.4 Add / update a SnapshotSet (explicit mode)

You can define membership using:
- `--snapshots` (labels; resolved to `head_sha` via `ImportRun`)
- `--head-shas` (explicit immutable SHAs)

Example (two snapshot labels):

```bash
python -m tools.weaviate.snapshot_sets --env add \
  --id nopCommerce_4-60_4-90 \
  --repo nopCommerce \
  --snapshots release-4.60.0 release-4.90.0 \
  --description "Public subset: 4.60 + 4.90"
```

Example (explicit SHAs):

```bash
python -m tools.weaviate.snapshot_sets --env add \
  --id nopCommerce_4-60_4-90 \
  --repo nopCommerce \
  --head-shas dcfbf411edb1756d9e8d10721be7b16b9649b34f 0123456789abcdef0123456789abcdef01234567
```

Mark as inactive:

```bash
python -m tools.weaviate.snapshot_sets --env add \
  --id nopCommerce_4-60_4-90 \
  --repo nopCommerce \
  --snapshots release-4.60.0 release-4.90.0 \
  --inactive
```

### 4.5 Delete a SnapshotSet

```bash
python -m tools.weaviate.snapshot_sets --env delete --id nopCommerce_release-4-60-0_release-4-90-0
```

Optional safety check:

```bash
python -m tools.weaviate.snapshot_sets --env delete \
  --id nopCommerce_release-4-60-0_release-4-90-0 \
  --repo nopCommerce

### 4.6 Purge a Snapshot (data + SnapshotSets)

Deletes:
- `RagNode` + `RagEdge` data for the snapshot
- `ImportRun` metadata rows for the snapshot
- Removes the snapshot from all SnapshotSets
- If a SnapshotSet becomes empty, it is **deleted**

Interactive (recommended):

```bash
python -m tools.weaviate.snapshot_sets --env purge-snapshot
```

With repo filter:

```bash
python -m tools.weaviate.snapshot_sets --env purge-snapshot --repo Fake
```

Non-interactive:

```bash
python -m tools.weaviate.snapshot_sets --env purge-snapshot --select 3 --yes
```
```

---

## 5) Common CLI failures

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
