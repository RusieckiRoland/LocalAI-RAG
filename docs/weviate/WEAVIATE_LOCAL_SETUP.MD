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

- Docker + Docker Compose
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

> Note: You may see `404` for `/v1/.well-known/openid-configuration` in local dev logs. That is normal when OIDC is not enabled.

---

## 3) Python environment (importer)

The importer writes objects into Weaviate:
- `ImportRun` — import registry / operational log
- `RagNode` — chunk objects (text + metadata + vector)
- `RagEdge` — graph edges (from/to + type)

Install dependencies (minimum):

```bash
pip install -U weaviate-client sentence-transformers
```

If you use a repository conda env file, ensure it includes:

- `weaviate-client`
- `sentence-transformers`

---

## 4) Import a bundle (branch or tag)

Importer script:

```
tools/weaviate/import_branch_to_weaviate.py
```

It accepts a bundle path that is either:
- a **folder** containing `repo_meta.json`, or
- a **.zip** containing `repo_meta.json`

### Example: import a tag bundle (.zip)

```bash
python tools/weaviate/import_branch_to_weaviate.py \
  --bundle repositories/nopCommerce/branches/release-4.90.0.zip \
  --embed-model models/embedding/e5-base-v2 \
  --weaviate-http-port 18080 \
  --weaviate-grpc-port 15005 \
  --ref-type tag \
  --ref-name release-4.90.0 \
  --tag release-4.90.0
```

### Important: `head_sha` partitioning

All data is queried by a concrete **`head_sha`**.
Every `RagNode` and `RagEdge` stores:
- `repo`
- `branch`
- `head_sha`

So you can run multiple snapshots side-by-side inside one Weaviate instance.

---

## 5) Verify import

### 5.1 Check ImportRun (import registry)

```bash
curl -s "http://localhost:18080/v1/objects?class=ImportRun&limit=5" | python -m json.tool
```

### 5.2 Count nodes / edges for one snapshot (`head_sha`)

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

### 5.3 Quick semantic query (nearVector + metadata filters)

You compute the query embedding locally and send it to Weaviate:

```python
import json, requests
from sentence_transformers import SentenceTransformer

head_sha = "PUT_SHA_HERE"
model = SentenceTransformer("models/embedding/e5-base-v2")

q = "entry point Program.cs Startup.cs Main"
vec = model.encode([q], normalize_embeddings=True)[0].tolist()

payload = {
  "query": f"""{{
    Get {{
      RagNode(
        nearVector: {{ vector: {json.dumps(vec)} }}
        where: {{
          operator: And
          operands: [
            {{path:["head_sha"], operator: Equal, valueText: "{head_sha}"}},
            {{path:["file_type"], operator: Equal, valueText: "cs"}}
          ]
        }}
        limit: 5
      ) {{
        canonical_id
        source_file
        repo_relative_path
        class_name
        member_name
        chunk_part
        chunk_total
        _additional {{ distance }}
      }}
    }}
  }}"""
}

r = requests.post("http://localhost:18080/v1/graphql", json=payload, timeout=120)
print(json.dumps(r.json(), indent=2)[:3000])
```

---

## 6) Reset / wipe the local database (dev)

If you want to re-import from scratch, the simplest and safest method locally:

```bash
docker compose -f weaviate-local/docker-compose.yml down -v
docker compose -f weaviate-local/docker-compose.yml up -d
```

`-v` removes the persistent volume (`weaviate_data`) and **erases all stored data**.

---

## 7) Production security (required)

**Do not run production with anonymous access enabled.**

Minimum baseline:
1) Disable anonymous access
2) Enable API key auth
3) Put Weaviate behind network controls (firewall / private network / reverse proxy + TLS)

### 7.1 Enable API keys (simple production baseline)

Example environment settings:

```yaml
environment:
  AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "false"
  AUTHENTICATION_APIKEY_ENABLED: "true"
  AUTHENTICATION_APIKEY_ALLOWED_KEYS: "YOUR_KEY_1,YOUR_KEY_2"
  AUTHENTICATION_APIKEY_USERS: "roland,service-account"
```

**Important:** Never commit API keys to git. Use:
- `.env` files ignored by git, or
- secret manager / container orchestration secrets, or
- environment variables injected by CI/CD

### 7.2 Querying with API key

When API keys are enabled, add an auth header:

```bash
API_KEY="YOUR_KEY_1"

curl -s http://localhost:18080/v1/meta \
  -H "Authorization: Bearer $API_KEY" \
| python -m json.tool
```

GraphQL example:

```bash
API_KEY="YOUR_KEY_1"

curl -s http://localhost:18080/v1/graphql \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ Aggregate { RagNode { meta { count } } } }"}' \
| python -m json.tool
```

### 7.3 Recommended production hardening

- Bind Weaviate to a private network (do not expose ports publicly)
- Use TLS (reverse proxy, e.g., nginx/traefik) if you must expose it
- Rotate API keys and keep separate keys for:
  - interactive user access
  - service-to-service access
- Consider OIDC/JWT for enterprise setups (SSO) instead of static keys

---

## 8) Troubleshooting (common)

### “Bundle path must be a folder or .zip”
You passed a path that does not exist from the current working directory.

- Use a correct relative path:
  - `repositories/.../release-4.90.0.zip`
- Or use an absolute path that actually exists.

### ImportRun shows `repo=unknown-repo`
Your bundle's `repo_meta.json` does not contain repo name fields.
The importer will try to infer repo name from `RepositoryRoot` (last folder name).

### Duplicates in SQL nodes/edges
Some SQL bundles may contain repeated keys/edges. The importer canonicalizes IDs and will naturally de-duplicate by UUID.
This is expected if your source data contains duplicates.

---

## 9) What gets created in Weaviate

After the first import, the following collections exist:

- `ImportRun`
  - operational log of imports: `repo`, `branch`, `head_sha`, `tag`, `friendly_name`, stats, status
- `RagNode`
  - chunk objects: `text`, metadata, `head_sha` partition fields, and the vector
- `RagEdge`
  - dependency edges: `edge_type`, `from_canonical_id`, `to_canonical_id`, `head_sha`
