# Weaviate – recommended starter commands (test repos)

This document shows the **typical command flow** for working with Weaviate in this repo, using the **test bundles** (fake snapshots) that are committed for future tests.

Assumptions:
- You run commands from the repo root: `LocalAI-RAG/`
- You keep secrets in `.env` (not committed) and you pass `--env` to CLIs when needed.
- Weaviate is already running (see `weaviate_local_setup.md`).

---

## 0) Quick sanity checks

```bash
curl -s http://localhost:18080/v1/meta | python -m json.tool
curl -s http://localhost:18080/v1/.well-known/ready
```

Optional: confirm your CLI can see `.env` (it loads only when `--env` is provided):

```bash
python -m tools.weaviate.snapshot_sets --env list
```

---

## 1) Import the test snapshots (fake bundles)

### 1.1 Import 4.60

```bash
python -m tools.weaviate.import_branch_to_weaviate --env \
  --bundle /home/roland/Repo/RAG_TEST_ENV/LocalAI-RAG/tests/repositories/fake/Release_FAKE_UNIVERSAL_4.60.zip \
  --embed-model models/embedding/e5-base-v2 \
  --ref-type branch \
  --ref-name Release_FAKE_UNIVERSAL_4.60
```

### 1.2 Import 4.90

```bash
python -m tools.weaviate.import_branch_to_weaviate --env \
  --bundle /home/roland/Repo/RAG_TEST_ENV/LocalAI-RAG/tests/repositories/fake/Release_FAKE_UNIVERSAL_4.90.zip \
  --embed-model models/embedding/e5-base-v2 \
  --ref-type branch \
  --ref-name Release_FAKE_UNIVERSAL_4.90
```

> If an import fails with “`repo_meta.json not found`”, verify the ZIP content:
>
> ```bash
> unzip -l /home/roland/Repo/RAG_TEST_ENV/LocalAI-RAG/tests/repositories/fake/Release_FAKE_UNIVERSAL_4.60.zip | head -n 40
> ```
>
> The importer expects `repo_meta.json` **at the archive root**.

---

## 2) List imported snapshots (what you can use in SnapshotSets)

Snapshot membership is driven by **ImportRun** records (each import has an immutable `snapshot_id`).

### 2.1 Show the last 20 imports (recommended)

```bash
curl -s http://localhost:18080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON' | python -m json.tool
{
  "query": "{ Get { ImportRun(limit:20){ repo branch ref_type ref_name tag snapshot_id head_sha status started_utc finished_utc } } }"
}
JSON
```

What to look for:
- `repo` (this is what you must pass as `--repo` when creating a SnapshotSet)
- `ref_name` / `branch` / `tag` (your human-readable label)
- `snapshot_id` (immutable selector for queries; also the tenant id)
- `head_sha` (informational only)

### 2.2 Resolve `snapshot_id` by branch name (optional)

```bash
BRANCH="Release_FAKE_UNIVERSAL_4.60"

curl -s http://localhost:18080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d @- <<JSON | python -m json.tool
{
  "query": "{ Get { ImportRun(where:{path:[\"branch\"],operator:Equal,valueText:\"${BRANCH}\"}, limit:5){ repo branch snapshot_id head_sha status finished_utc } } }"
}
JSON
```

---

## 3) Create a SnapshotSet from the imported fake snapshots

Pick the correct repo name from ImportRun (section 2). Below, we assume it is `fake`.
If your ImportRun shows something else, use that value instead.

### 3.1 Create (or update) SnapshotSet

```bash
python -m tools.weaviate.snapshot_sets --env add \
  --id fakeSnapSet \
  --repo fake \
  --refs Release_FAKE_UNIVERSAL_4.60 Release_FAKE_UNIVERSAL_4.90 \
  --description "Test browsing scope: FAKE 4.60 + 4.90"
```

Notes:
- `--refs ...` are resolved to `head_sha` via `ImportRun`.
- You can also pass `--head-shas ...` directly if needed.

---

## 4) Verify / inspect SnapshotSets

### 4.1 List SnapshotSets

```bash
python -m tools.weaviate.snapshot_sets --env list
```

Filter by repo:

```bash
python -m tools.weaviate.snapshot_sets --env list --repo fake
```

### 4.2 Show one SnapshotSet (details)

```bash
python -m tools.weaviate.snapshot_sets --env show --id fakeSnapSet
```

---

## 5) Delete a SnapshotSet

```bash
python -m tools.weaviate.snapshot_sets --env delete --id fakeSnapSet
```

Optional safety check (expected repo):

```bash
python -m tools.weaviate.snapshot_sets --env delete --id fakeSnapSet --repo fake
```

---

## 6) Common failures (quick fixes)

### `401 Unauthorized`
- Weaviate has API key auth enabled
- Your shell does not have `WEAVIATE_API_KEY` exported
- Fix: put it into `.env` and run CLI with `--env`

### Too much httpx noise in output
- If your CLI has `--verbose`, keep it OFF by default.
- If not: set `HTTPX_LOG_LEVEL=WARNING` or configure logging in the CLI to silence `httpx` unless verbose is enabled.
