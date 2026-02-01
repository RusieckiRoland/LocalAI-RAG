# Weaviate CLI (repository / snapshot management)

This document describes the CLI tools that manage repository snapshots stored in Weaviate.

These tools assume Weaviate is already running (see `WEAVIATE_LOCAL_SETUP.md`).

---

## 1) Connection and auth model

### 1.1 Sources of connection settings

Connection settings are resolved in this order:

1) CLI flags (if provided)
2) Environment variables (e.g., `WEAVIATE_API_KEY`)
3) `config.json` (`weaviate.host/http_port/grpc_port/...`)
4) Defaults (localhost / 18080 / 15005)

### 1.2 `.env` loading (`--env`)

`.env` is **not** loaded automatically by your shell.

All CLI tools support:

- `--env`  
  Loads `<repo_root>/.env` for the current process **without overriding** already-set environment variables.

Use `--env` when your API key is stored in `.env` and you run the CLI from a clean shell.

---

## 2) Import a snapshot bundle into Weaviate

Script:

```
tools/weaviate/import_branch_to_weaviate.py
```

Typical usage (dev, with `.env`):

```bash
python tools/weaviate/import_branch_to_weaviate.py --env \
  --bundle repositories/nopCommerce/branches/release-4.60.0.zip \
  --embed-model models/embedding/e5-base-v2 \
  --ref-type tag \
  --ref-name release-4.60.0 \
  --tag release-4.60.0
```

If you want to override the API key explicitly (not recommended for shells with history):

```bash
python tools/weaviate/import_branch_to_weaviate.py \
  --bundle repositories/nopCommerce/branches/release-4.60.0.zip \
  --embed-model models/embedding/e5-base-v2 \
  --weaviate-api-key "<KEY>" \
  --ref-type tag \
  --ref-name release-4.60.0 \
  --tag release-4.60.0
```

Importer flags (high-level):
- `--bundle` (required): folder or `.zip` containing `repo_meta.json`
- `--embed-model` (required): SentenceTransformer model path/name
- `--env`: load `<repo_root>/.env`
- Optional overrides:
  - `--weaviate-host`, `--weaviate-http-port`, `--weaviate-grpc-port`
  - `--weaviate-api-key`

---

## 3) Discover snapshot `head_sha` for a tag/branch

Imports are recorded in the `ImportRun` collection. Each import resolves to one immutable `head_sha`.

Example: resolve `head_sha` for a tag:

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

Use the returned `head_sha` as the partition filter for queries against `RagNode` / `RagEdge`.

---

## 4) SnapshotSets (query scopes)

A **SnapshotSet** is a named “query scope” that restricts which snapshots (immutable `head_sha` values) are allowed for a given repo.

Script:

```
tools/weaviate/snapshot_sets.py
```

Commands:
- `list`   — list SnapshotSets
- `show`   — show details for one SnapshotSet
- `add`    — create or update a SnapshotSet
- `delete` — delete a SnapshotSet

### 4.1 List SnapshotSets

```bash
python tools/weaviate/snapshot_sets.py --env list
```

Filter by repo:

```bash
python tools/weaviate/snapshot_sets.py --env list --repo nopCommerce
```

JSON output:

```bash
python tools/weaviate/snapshot_sets.py --env list --format json
```

### 4.2 Show a SnapshotSet

```bash
python tools/weaviate/snapshot_sets.py --env show --id nopCommerce_4-60_4-90
```

### 4.3 Add / update a SnapshotSet

You can define membership using:
- `--refs` (branch/tag names) which are resolved to `head_sha` using `ImportRun`
- `--head-shas` (explicit immutable head SHAs)

Example: allow two tags:

```bash
python tools/weaviate/snapshot_sets.py --env add \
  --id nopCommerce_4-60_4-90 \
  --repo nopCommerce \
  --refs release-4.60.0 release-4.90.0 \
  --description "Public subset: 4.60 + 4.90"
```

Example: allow explicit SHAs:

```bash
python tools/weaviate/snapshot_sets.py --env add \
  --id nopCommerce_4-60_4-90 \
  --repo nopCommerce \
  --head-shas dcfbf411edb1756d9e8d10721be7b16b9649b34f 0123456789abcdef0123456789abcdef01234567
```

Mark as inactive:

```bash
python tools/weaviate/snapshot_sets.py --env add \
  --id nopCommerce_4-60_4-90 \
  --repo nopCommerce \
  --refs release-4.60.0 release-4.90.0 \
  --inactive
```

### 4.4 Delete a SnapshotSet

```bash
python tools/weaviate/snapshot_sets.py --env delete --id nopCommerce_4-60_4-90
```

Optional safety check (expected repo):

```bash
python tools/weaviate/snapshot_sets.py --env delete --id nopCommerce_4-60_4-90 --repo nopCommerce
```

---

## 5) Common CLI failures

### `401 Unauthorized`
Weaviate has API key auth enabled but your CLI did not send a key.

Fix:
- Put the key into `.env` as `WEAVIATE_API_KEY=...`
- Run the tool with `--env`, or export the variable in your shell.

### `.env` was loaded but API key is still empty
Ensure your `.env` contains:

```env
WEAVIATE_API_KEY=your-real-key-here
```

And that you are running with `--env`.

### `Connection refused`
Weaviate is not running, or ports mismatch. Check:

```bash
docker ps | grep weaviate || true
curl -sS http://localhost:18080/v1/meta | head
```


## Resolve `head_sha`


### Resolve `head_sha` (by branch)

```bash
BRANCH="release-4.60.0"

curl -s http://localhost:18080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ Get { ImportRun(where:{path:[\\\"branch\\\"],operator:Equal,valueText:\\\"$BRANCH\\\"}, limit:5){ repo branch tag head_sha status } } }\"}" \
| python -m json.tool
```

