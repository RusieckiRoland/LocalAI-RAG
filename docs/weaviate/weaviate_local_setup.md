# Weaviate Local Setup (Weaviate-only / BYOV)

This repository uses **Weaviate as the only retrieval backend**.

- **No FAISS** is used anywhere in the retrieval path.
- You compute embeddings locally (BYOV — *Bring Your Own Vectors*).
- Weaviate stores **vectors + metadata + text** and performs:
  - Vector search (HNSW/ANN)
  - BM25 search
  - Hybrid search
  - Metadata pre-filtering (e.g., `head_sha`, `file_type`, ACL fields)

---

## 1) Prerequisites

- Docker + Docker Compose (Compose v2 recommended: `docker compose ...`)
- Python 3.11
- A local embedding model compatible with `sentence-transformers`
  - Example used below: `models/embedding/e5-base-v2`

---

## 2) Start Weaviate locally (Docker Compose)

Create / edit:

```
weaviate-local/docker-compose.yml
```

Recommended local (dev) compose:

```yaml
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.34.0
    ports:
      - "18080:8080"   # HTTP API
      - "15005:50051"  # gRPC
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"

      # BYOV (no built-in vectorizer)
      DEFAULT_VECTORIZER_MODULE: "none"
      ENABLE_MODULES: ""

      # Local dev only
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"

      CLUSTER_HOSTNAME: "node1"
    volumes:
      - weaviate_data:/var/lib/weaviate

volumes:
  weaviate_data:
```

Notes:
- Keep the Weaviate image tag pinned (avoid `latest`).
- Ensure the running container version matches the compose file.
 - If you are on Weaviate `1.32.2`, BM25 `AND` via gRPC can time out (`Deadline Exceeded`). Upgrading to `1.32.17` or newer resolves the timeout. After upgrade, `AND` can still be very strict and may yield `0` hits; fall back to `OR`/none if needed.

Start:

```bash
docker compose -f weaviate-local/docker-compose.yml up -d
docker ps | grep weaviate
```

Health check:

```bash
curl -s http://localhost:18080/v1/meta | python -m json.tool
curl -s http://localhost:18080/v1/.well-known/ready
```

> You may see `404` for `/v1/.well-known/openid-configuration` in local dev logs. This is normal when OIDC is not enabled.

---

## 2.1) Optional: Autostart on WSL boot (systemd)

If you want Weaviate to start automatically when WSL starts:

### 2.1.1 Enable systemd in WSL

Edit:

`/etc/wsl.conf`

```ini
[boot]
systemd=true
```

Restart WSL from Windows (PowerShell):

```powershell
wsl --shutdown
```

After relaunching WSL, verify:

```bash
ps -p 1 -o comm=
# expected: systemd
```

### 2.1.2 Create a systemd unit for Weaviate (docker compose)

Create:

`/etc/systemd/system/weaviate-local.service`

```ini
[Unit]
Description=Weaviate local (docker compose)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes

# Wait until Docker is ready (important if you use Docker Desktop + WSL integration)
ExecStartPre=/bin/bash -lc 'for i in {1..60}; do docker info >/dev/null 2>&1 && exit 0; sleep 1; done; echo "Docker not ready"; exit 1'

# Adjust to your repo checkout path:
WorkingDirectory=/home/<user>/Repo/RAG_TEST_ENV/LocalAI-RAG/weaviate-local

ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

Enable + start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable weaviate-local.service
sudo systemctl start weaviate-local.service
systemctl status weaviate-local.service --no-pager
```

---

## 3) Repository configuration files

### 3.1 `config.json` (committed)

Weaviate connection **non-secrets** live in `config.json` under a `weaviate` section:

```json
{
  "weaviate": {
    "host": "localhost",
    "http_port": 18080,
    "grpc_port": 15005
  }
}
```

This is safe to commit: host/ports/timeouts are not secrets.

### 3.2 `.env` (NOT committed) and `.env.example` (committed)

- `.env.example` is committed as a checklist of variables that may be required.
- `.env` is NOT committed and stores secrets / local overrides.

Example `.env.example` snippet:

```env
# === Weaviate (secrets) ===
WEAVIATE_API_KEY=
```

Important:
- `.env` is **not** loaded automatically by the shell.
- Our CLI tools and server support an explicit `--env` flag (see `weaviate_cli.md`) to load `<repo_root>/.env` for that process.
- In production, prefer real environment injection (systemd `EnvironmentFile=...`, CI/CD secrets, etc.).

---

## 4) Python environment (importer + CLI)

Minimum dependencies:

```bash
pip install -U weaviate-client sentence-transformers
```

If you use a conda env, ensure it includes:

- `weaviate-client`
- `sentence-transformers`

---

## 5) Verify Weaviate is reachable

```bash
curl -s http://localhost:18080/v1/meta | python -m json.tool
curl -s http://localhost:18080/v1/.well-known/ready
```

---


---

## 7) Verify your import

These checks confirm that:
- Weaviate is reachable
- your snapshot exists (`ImportRun`)
- you can resolve `head_sha` from tag/branch
- nodes + edges are present for that `head_sha`
- vector search works (`nearVector`)

### 7.1 List recent imports (ImportRun)

```bash
curl -s "http://localhost:18080/v1/graphql" \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ Get { ImportRun(limit:10, sort:[{path:[\"ts_utc\"], order:desc}]) { repo branch tag head_sha friendly_name status ts_utc } } }"}' \
| python -m json.tool
```

### 7.2 Resolve `head_sha` by **tag**

```bash
TAG="release-4.60.0"

curl -s "http://localhost:18080/v1/graphql" \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ Get { ImportRun(where:{path:[\\\"tag\\\"],operator:Equal,valueText:\\\"$TAG\\\"}, limit:5){ repo branch tag head_sha status } } }\"}" \
| python -m json.tool
```

### 7.3 Resolve `head_sha` by **branch**

```bash
BRANCH="release-4.60.0"

curl -s "http://localhost:18080/v1/graphql" \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ Get { ImportRun(where:{path:[\\\"branch\\\"],operator:Equal,valueText:\\\"$BRANCH\\\"}, limit:5){ repo branch tag head_sha status } } }\"}" \
| python -m json.tool
```

### 7.4 Count nodes and edges for one `head_sha`

```bash
HEAD_SHA="PUT_SHA_HERE"

curl -s http://localhost:18080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ Aggregate { RagNode(where:{path:[\\\"head_sha\\\"], operator:Equal, valueText:\\\"$HEAD_SHA\\\"}) { meta { count } } } }\"}" \
| python -m json.tool

curl -s http://localhost:18080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ Aggregate { RagEdge(where:{path:[\\\"head_sha\\\"], operator:Equal, valueText:\\\"$HEAD_SHA\\\"}) { meta { count } } } }\"}" \
| python -m json.tool
```

### 7.5 Quick `nearVector` smoke test (Python, BYOV)

```python
import os, json, requests
from sentence_transformers import SentenceTransformer

head_sha = "PUT_SHA_HERE"
model = SentenceTransformer("models/embedding/e5-base-v2")

q = "entry point Program.cs Startup.cs Main"
vec = model.encode([q], normalize_embeddings=True)[0].tolist()

headers = {"Content-Type": "application/json"}
api_key = (os.getenv("WEAVIATE_API_KEY") or "").strip()
if api_key:
    headers["Authorization"] = f"Bearer {api_key}"

query = (
  "{ Get { RagNode("
  "  nearVector: { vector: " + json.dumps(vec) + " }"
  "  where: { operator: And, operands: ["
  f"    {{path:[\"head_sha\"], operator: Equal, valueText: \"{head_sha}\"}},"
  "    {path:[\"file_type\"], operator: Equal, valueText: \"cs\"}"
  "  ] }"
  "  limit: 5"
  ") { canonical_id repo_relative_path class_name member_name _additional { distance } } } }"
)

r = requests.post("http://localhost:18080/v1/graphql", json={"query": query}, headers=headers, timeout=120)
print(json.dumps(r.json(), indent=2)[:3000])
```


## 8) Reset / wipe the local database (dev)

To re-import from scratch:

```bash
docker compose -f weaviate-local/docker-compose.yml down -v
docker compose -f weaviate-local/docker-compose.yml up -d
```

`-v` removes the persistent volume (`weaviate_data`) and erases all stored data.

---

## 9) Production security (required)

**Do not run production with anonymous access enabled.**

Minimum baseline:
1) Disable anonymous access
2) Enable API key auth
3) Put Weaviate behind network controls (firewall / private network / reverse proxy + TLS)

Example compose environment settings:

```yaml
environment:
  AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "false"
  AUTHENTICATION_APIKEY_ENABLED: "true"
  AUTHENTICATION_APIKEY_ALLOWED_KEYS: "YOUR_KEY_1,YOUR_KEY_2"
  AUTHENTICATION_APIKEY_USERS: "userName,service-account"
```

Important:
- Never commit API keys to git.
- Prefer secret injection via `.env` (ignored) or platform secret managers.

Querying with API key (direct curl):

```bash
API_KEY="YOUR_KEY_1"
curl -s http://localhost:18080/v1/meta \
  -H "Authorization: Bearer $API_KEY" \
| python -m json.tool
```

---

## 10) Troubleshooting (common)

### `docker: 'compose' is not a docker command`
You are missing Compose v2.

Install from the official Docker repo (Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-compose-plugin

docker compose version
```

### systemd service fails (exit code 125)
Inspect logs:

```bash
journalctl -xeu weaviate-local.service --no-pager | tail -n 80
```

Common causes:
- `docker compose` not installed at `/usr/bin/docker`
- Wrong `WorkingDirectory` path
- Docker not ready yet (WSL/Docker Desktop timing)

### `WeaviateConnectionError: Connection refused (localhost:18080)`
Weaviate is not running or ports do not match.

Check:

```bash
docker ps | grep weaviate || true
curl -sS http://localhost:18080/v1/meta | head
ss -ltnp | egrep '(:18080|:15005)\b' || true
```

### `401 Unauthorized`
Weaviate has API key auth enabled but your client did not send a key.

Fix:
- Ensure `WEAVIATE_API_KEY` is set (or pass `--weaviate-api-key` in CLI).
- If using `.env`, run tools with `--env` (see `weaviate_cli.md`).

---

## 11) What gets created in Weaviate

After the first import, the following collections exist:

- `ImportRun`
  - operational log of imports: `repo`, `branch`, `head_sha`, `tag`, `friendly_name`, stats, status
- `RagNode`
  - chunk objects: `text`, metadata, `head_sha` partition fields, and the vector
- `RagEdge`
  - dependency edges: `edge_type`, `from_canonical_id`, `to_canonical_id`, `head_sha`


---

## 5) Import snapshots (CLI quickstart)

> Full CLI documentation lives in `weaviate_cli.md`. This section is a **quickstart** so a new user can succeed without jumping between files.

### 5.1 `.env` and `--env` (important)

- `.env` is **not** loaded automatically by your shell.
- If your Weaviate API key is stored in `.env` as `WEAVIATE_API_KEY=...`, run CLI tools with `--env`.

Example:

```bash
python tools/weaviate/import_branch_to_weaviate.py --env -h
```

### 5.2 Import a tag snapshot

```bash
python tools/weaviate/import_branch_to_weaviate.py --env \
  --bundle repositories/nopCommerce/branches/release-4.60.0.zip \
  --embed-model models/embedding/e5-base-v2 \
  --ref-type tag \
  --ref-name release-4.60.0 \
  --tag release-4.60.0
```

### 5.3 Import a branch snapshot

```bash
python tools/weaviate/import_branch_to_weaviate.py --env \
  --bundle repositories/nopCommerce/branches/release-4.60.0.zip \
  --embed-model models/embedding/e5-base-v2 \
  --ref-type branch \
  --ref-name release-4.60.0
```

---

## 6) SnapshotSets (query scopes) – essentials

A **SnapshotSet** is a named query scope that restricts which snapshots (immutable `head_sha` values) are allowed for a given repo.
This is the mechanism that lets you expose only selected versions (e.g. `release-4.60.0`, `release-4.90.0`) to users/pipelines.

> Full SnapshotSet CLI documentation (all flags) lives in `weaviate_cli.md`. Below are the essentials.

### 6.1 List SnapshotSets

```bash
python tools/weaviate/snapshot_sets.py --env list
```

### 6.2 Show one SnapshotSet

```bash
python tools/weaviate/snapshot_sets.py --env show --id nopCommerce_4-60_4-90
```

### 6.3 Create / update a SnapshotSet by refs (tag/branch → head_sha)

```bash
python tools/weaviate/snapshot_sets.py --env add \
  --id nopCommerce_4-60_4-90 \
  --repo nopCommerce \
  --refs release-4.60.0 release-4.90.0 \
  --description "Public subset: 4.60 + 4.90"
```

### 6.4 Delete a SnapshotSet

```bash
python tools/weaviate/snapshot_sets.py --env delete --id nopCommerce_4-60_4-90
```
