# 🧠 GPU‑Accelerated RAG with Weaviate (BYOV) + LLaMA

> **Weaviate-only backend:** This project uses **Weaviate** as the single retrieval backend (BM25 + hybrid + vector search + metadata filtering).
> **FAISS is not used** anywhere in this project.

**Target platform:** Linux or WSL2 • **Python:** 3.11 • **GPU:** NVIDIA (CUDA) • **Package manager:** Conda

**Purpose.** Build a **local, GPU‑accelerated knowledge base for your source code**: index it, analyze it, and **search/query it with AI**. The system runs **fully on‑premises** — no source code leaves your network; models execute on your GPU.

---

## Architectural Core Principle: Flexibility

The system is built around **dynamic pipelines defined in YAML files**.  
You can treat pipelines like building blocks (actions) and assemble them as needed:

- easily change the order of processing steps
- add / disable actions (translation, routing, search, answer generation…)
- define your own prompts, filters, context limits, and policies
- create different work modes (code analysis, UML diagrams, branch comparison)
- reuse and extend existing YAML pipelines via inheritance, eliminating the need to redefine everything from scratch.

Think of it as **pipeline composition by configuration**, not by code — just like configuring a workflow in a YAML file.

**At a glance**

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ translate    │→→│ load_history │→→│   search     │→→│ fetch        │→→│   answer     │→→ ....
│ (Query)      │  │ (YAML step)  │  │ (YAML step)  │  │ (YAML step)  │  │ (YAML step)  │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
     ↑                          Each block is a configurable action in the YAML pipeline
```

### Pipeline reliability additions

- **Context divider for new retrieval batches:** `manage_context_budget` can insert a one-line marker
  (e.g., `<<<New content`) each time a new batch is appended to `state.context_blocks`. This makes
  “latest evidence” clearly visible to downstream prompts.
- **Sufficiency anti-repeat guard in prompt:** the `sufficiency_router_v1` prompt now includes
  `<<<LAST QUERY>` and `<<<PREVIOUS QUERIES>` injected from pipeline state, and explicitly forbids
  repeating or paraphrasing earlier retrieval queries.

More details, diagrams, and examples are available here:

→ **`docs/`** – full documentation of pipelines, actions, and configuration

### Minimal pipeline example (YAML)

```yaml
pipeline:
  id: "rejewski"
  steps:
    - id: "translate"
      action: "translate_in_if_needed"
      next: "load_history"

    - id: "load_history"
      action: "load_conversation_history"
      next: "search"

    - id: "search"
      action: "search_nodes"
      search_type: "hybrid"
      top_k: 8
      next: "expand"    

    - id: "fetch"
      action: "fetch_node_texts"
      top_n_from_settings: "node_text_fetch_top_n"
      next: "answer"

    - id: "answer"
      action: "call_model"
      prompt_key: "rejewski/answer_v1"
      next: "finalize"

    - id: "finalize"
      action: "finalize"
      end: true
```

**Hardware target.** Optimized for a **single NVIDIA RTX 4090** (CUDA 12.x). Defaults (e.g., full llama.cpp CUDA offload) are tuned to comfortably fit 24–32 GB VRAM.

**Stack focus.**

* **.NET/C# codebases** — deep static analysis via **Roslyn** (ASTs, symbols, references, call graphs) to extract rich, navigable context.
* **SQL & Entity Framework** — inspection of schemas, relationships and query usage to surface domain entities and data access patterns to the RAG layer.
* **Dependency graph of code fragments** — the index stores **links between chunks** (files, classes, methods) so retrieval can traverse relationships (e.g., callers/callees, type usages, EF entity links) and answer questions with proper context.

**Who is this for?** Organizations that **cannot send code to external services** (e.g., banks, financial institutions, operators of critical infrastructure) and must run **fully local** solutions.

---

## 1) Prerequisites

* Linux or WSL2 (Windows 11 recommended)
* NVIDIA GPU with recent drivers (for WSL2, ensure GPU passthrough works)
* Miniconda (or Anaconda)

Quick GPU sanity check:

```bash
nvidia-smi
```

You should see your GPU listed. If not, fix drivers/WSL2 before continuing.

Install Miniconda (if needed):

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
bash miniconda.sh
source ~/.bashrc
conda --version
```

---

## 2) Clone the repository

```bash
git clone <YOUR-REPO-URL>
cd <PROJECT-FOLDER>
```

> 🔒 **Models are not committed.** Each target folder already contains a `download_model.md` with instructions.

To index your .NET solution:

```bash
# 1. Clone the indexer
git clone https://github.com/RusieckiRoland/RoslynIndexer.git
cd RoslynIndexer

# 2. Run the indexer (see full README in that repo)
dotnet run --project ./RoslynIndexer.Net9/RoslynIndexer.Net9.csproj -- \
  --solution "D:\Repo\src\MySolution.sln" \
  --temp-root "D:\Work\"
```
**PowerShell**
``` PowerShell
git clone https://github.com/RusieckiRoland/RoslynIndexer.git
cd RoslynIndexer
dotnet run --project .\RoslynIndexer.Net9\RoslynIndexer.Net9.csproj -- `
  --solution "D:\Repo\src\MySolution.sln" `
  --temp-root "D:\Work\"
```
---

## 3) Create the environment

> We keep **llama‑cpp‑python** out of `environment.yml` to install the exact CUDA wheel after the env is created.

```bash
conda env create -f environment.yml
conda activate rag-weaviate
```

If you see a warning about `sacremoses`, install it (needed for some MarianMT models):

```bash
pip install sacremoses
```

### `environment.yml` (reference)

```yaml
name: rag-weaviate
channels:
  - pytorch
  - nvidia
  - conda-forge
dependencies:
  # --- Core environment pins ---
  - python=3.11.*
  - numpy=1.26.4
  - cuda-toolkit=12.1
  - pip

  # --- Pip dependencies ---
  - pip:
      - numpy==1.26.4
      - sentence-transformers
      - tqdm
      - flask
      - flask-cors
      - huggingface-hub
      - transformers
      - safetensors
      - sentencepiece
      - sacremoses
      - protobuf
      - mdpo
      - pytest
      - pytest-mock
      - diskcache         # ✅ Added manually for llama-cpp-python
      - jinja2            # ✅ Dependency also needed by llama-cpp-python
      - typing-extensions # ✅ Safe for PyTorch and llama-cpp-python
      - python-dotenv
      - weaviate-client

> ⚙️ **Note:**  
> The `environment.yml` shown above is **for reference only**.  
> It is meant to illustrate the key dependencies but may become outdated as the project evolves.  
> Always use and update the **actual `environment.yml` file** in the repository when creating or updating your Conda environment.

```

---

## 4) Install llama‑cpp‑python (CUDA build)

By default, `pip install llama-cpp-python` provides a CPU build. Install the **CUDA build** that matches your CUDA runtime (e.g., `cu121` for CUDA 12.1).

```bash
# remove any CPU build if present
pip uninstall -y llama-cpp-python

# install CUDA build
wget https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.16-cu121/llama_cpp_python-0.3.16-cp311-cp311-linux_x86_64.whl

pip install --no-deps llama_cpp_python-0.3.16-cp311-cp311-linux_x86_64.whl

# quick import check
python - <<'PY'
from llama_cpp import Llama, __version__
print("llama_cpp import OK, version:", __version__)
PY
```

---

## 5) Download models into the **existing** folders

### One‑shot downloader (`download_models.sh`) — **recommended**

A convenience script is provided at the **repo root**. It fetches all required models directly into the correct folders under `models/…`.

**Requirements:**

* Linux/WSL2 shell with `wget` and `huggingface-cli`

  * Install: `pip install --upgrade huggingface_hub`
  * If needed: `huggingface-cli login`

**Run from the repo root:**

```bash
chmod +x download_models.sh
./download_models.sh
```

The script writes into the **already existing** directories (it won’t invent new paths) and mirrors our repo layout. Downloaded weights are ignored by `.gitignore`.

**Quick verify:**

```bash
ls -lh models/code_analysis/codeLlama_13b_Instruct/*.gguf
ls -1  models/embedding/e5-base-v2 | wc -l
ls -1  models/translation/en_pl/Helsinki_NLPopus_mt_en_pl
ls -1  models/translation/pl_en/Helsinki-NLPopus-mt-pl-en
```

If any folder lacks files, use the fallback below.

---

### Fallback: per‑folder `download_model.md`

If something fails, or links change upstream, open the `download_model.md` located **inside each target folder** and execute its **copy‑paste commands** (run them from the **repo root**, do **not** create new directories):

* `code_analysis/codeLlama_13b_Instruct/download_model.md` → **code model (GGUF)**
* `embedding/e5-base-v2/download_model.md` → **embedding model**
* `translation/en_pl/Helsinki_NLPopus_mt_en_pl/download_model.md` → **EN→PL** translation
* `translation/pl_en/Helsinki-NLPopus-mt-pl-en/download_model.md` → **PL→EN** translation

> **Do not duplicate instructions in the README.** Use the commands from the `download_model.md` files **as‑is**, and place files only into the **existing** directories.

Git tracks **only** the `download_model.md` placeholders; all downloaded weights remain untracked.

**Do not proceed to tests until all four folders contain the downloaded files.**

---

## 6) Configuration files

### `config.json`

```json
{
  "output_dir": "branches",
  "model_path_embd": "models/embedding/e5-base-v2",
  "model_path_analysis": "models/code_analysis/codeLlama_13b_Instruct/CodeLlama-13b-Instruct-hf-Q8_0.gguf",
  "model_translation_en_pl": "models/translation/en_pl/Helsinki_NLPopus_mt_en_pl",
  "model_translation_pl_en": "models/translation/pl_en/Helsinki-NLPopus-mt-pl-en",
  "log_path": "log/ai_interaction.log",
  "use_gpu": true,
  "plantuml_server": "http://localhost:8080",
  "branch": "master"
}
```

**Description:**

* `output_dir` — directory where branch outputs and analysis results are written.
* `model_path_embd` — local path to the embedding model directory (e.g., E5-base-v2).
* `model_path_analysis` — path to the main code-analysis LLaMA model (GGUF).
* `model_translation_en_pl` / `model_translation_pl_en` — MarianMT model folders for EN→PL and PL→EN translation.
* `log_path` — file path for AI interaction logs.
* `use_gpu` — enables GPU acceleration for LLaMA and local embedding computation when `true`.
* `plantuml_server` — optional local PlantUML server endpoint.
* `branch` — default Git branch analyzed by the pipeline.

> Keep secrets out of `config.json`. If needed, commit `config.json.example` and create a local `config.json` from it.

---

### `.env.example`

```bash
APP_SECRET_KEY=change-me-to-a-long-random-string
API_TOKEN=your-internal-token-here
APP_DEVELOPMENT=1
IDP_AUTH_ENABLED=1

# === Server settings ===
APP_HOST=0.0.0.0
APP_PORT=5000

# === CORS / Origins ===
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080

# === Query limits (optional) ===
APP_MAX_QUERY_LEN=8000
APP_MAX_FIELD_LEN=128
```

**Description:**

* `APP_SECRET_KEY` — Flask session secret; use a long random string in production.
* `API_TOKEN` — internal API token for service-to-service calls.
* `APP_DEVELOPMENT` — overrides development endpoint exposure (`1` enables `/dev` endpoints, `0` hides them).
* `IDP_AUTH_ENABLED` — forces IDP JWT validation on `prod` endpoints (`1`) or disables it (`0`).
* `APP_HOST` / `APP_PORT` — bind address and port of the Flask app.
* `ALLOWED_ORIGINS` — comma-separated list of allowed CORS origins.
* `APP_MAX_QUERY_LEN` / `APP_MAX_FIELD_LEN` — optional server-side limits for incoming requests.

### IDP settings in `config.json`

`prod` auth can validate JWT tokens against your identity provider:

```json
"identity_provider": {
  "enabled": true,
  "issuer": "https://idp.example.com/realms/localai-rag",
  "jwks_url": "https://idp.example.com/realms/localai-rag/protocol/openid-connect/certs",
  "audience": "localai-rag-api",
  "algorithms": ["RS256"],
  "required_claims": ["sub", "exp", "iss", "aud"]
}
```

Install JWT verification dependency in your active environment:

```bash
python -m pip install "pyjwt[crypto]"
```

**Setup:** copy the example file before running the app and adjust values:

```bash
cp .env.example .env
```
---

## 7) Verify GPU acceleration (**run after models are in place**)

### A) LLaMA (llama‑cpp‑python)

Run this **one‑liner quick test** (copy‑paste) **after Step 5**. It auto‑detects the model under `code_analysis/...` or `models/code_analysis/...`, loads with full CUDA offload, and prints a clear success message in English. **Copy‑paste safe — no unfinished strings.**

```bash
conda activate rag-weaviate
python - <<'PY'
import glob, os, sys, time
from llama_cpp import Llama

print("CWD:", os.getcwd())

patterns = [
    "code_analysis/codeLlama_13b_Instruct/*.gguf",
    "models/code_analysis/codeLlama_13b_Instruct/*.gguf",
    "RAG/code_analysis/codeLlama_13b_Instruct/*.gguf",
    "RAG/models/code_analysis/codeLlama_13b_Instruct/*.gguf",
    "**/codeLlama_13b_Instruct/*.gguf",  # fallback (recursive)
]
matches = []
for pat in patterns:
    matches.extend(glob.glob(pat, recursive=True))

matches = sorted(set(matches))
if not matches:
    sys.exit(
        "ERROR: no .gguf found. Expected under one of:\n"
        "  - code_analysis/codeLlama_13b_Instruct/\n"
        "  - models/code_analysis/codeLlama_13b_Instruct/\n"
        "  - RAG/... equivalents\n"
        "Follow the download_model.md and retry."
    )

print("Found models:")
for m in matches:
    print("  -", m)

model_path = max(matches, key=os.path.getsize)  # pick the largest
print("Using model:", model_path)

t0 = time.time()
llm = Llama(model_path=model_path, n_ctx=2048, n_gpu_layers=-1, verbose=True)
out = llm("Q: What is the capital of France? A:", max_tokens=16, stop=["\n", "Q:", "User:", "###"])
dt = time.time() - t0
answer = out["choices"][0]["text"].strip()
print("Answer:", answer)

print("\n✅ OK: Model loaded and generated successfully.")
print("   GPU acceleration: CUDA offload requested (n_gpu_layers = -1).")
print("   If you saw 'using device CUDA' above, the model is running on your GPU.")
print(f"   Elapsed: {dt:.2f}s. You can proceed to the next step.")
PY
```

**Expected:** llama.cpp logs show CUDA offload and a message starting with `✅ OK: Model loaded and generated successfully.`

---

## 8) Typical project layout (models section)

```
models/
├─ code_analysis/
│  └─ codeLlama_13b_Instruct/
│     ├─ CodeLlama-13b-Instruct-hf-Q8_0.gguf    # (ignored by Git)
│     └─ download_model.md                      # tracked
├─ embedding/
│  └─ e5-base-v2/
│     ├─ [HF files: config.json, *.bin, *.safetensors, tokenizer.json, etc.]  # weights/tokenizer (ignored by Git)
│     └─ download_model.md                      # tracked
├─ translation/
   ├─ en_pl/
   │  └─ Helsinki_NLPopus_mt_en_pl/
   │     ├─ [MarianMT files: config.json, *.bin, *.safetensors, sentencepiece.model]  # (ignored by Git)
   │     └─ download_model.md                    # tracked
   └─ pl_en/
      └─ Helsinki-NLPopus-mt-pl-en/
         ├─ [MarianMT files: config.json, *.bin, *.safetensors, sentencepiece.model]  # (ignored by Git)
         └─ download_model.md                   # tracked

```
---

## 8) Weaviate local setup

Weaviate setup is documented in a separate file:

- `weaviate_local_setup.md`

## 8.5) Branch preparation guide

1. **Create the output folder** defined in your `config.json` — e.g.:

   ```json
   {
     "output_dir": "branches"
   }
   ```

   Create this folder at the repository root (use the exact name from `output_dir`).

2. Follow the instructions in **[`HOW_TO_PREPARE_REPO.md`](./HOW_TO_PREPARE_REPO.md)** located in the repository root. It explains how to index the repository and then build the retrieval store in Weaviate (BYOV) from the generated chunks.

---

## 9) Troubleshooting

* **`llama-cpp-python` runs on CPU**: You likely installed the CPU wheel. Reinstall a **CUDA** wheel matching your CUDA (e.g., `cu121`). Ensure `verbose=True` and check logs.
* **`nvidia-smi` not found in WSL**: Update WSL and Windows NVIDIA drivers; reboot and retry.
* **Weaviate BM25 `AND` timeouts (gRPC)**: On Weaviate `1.32.2` the gRPC BM25 operator `AND` can hang and end in `Deadline Exceeded`, even though the same BM25 query works via GraphQL. Upgrading Weaviate (e.g., `1.32.17` or newer) fixes the timeout. After upgrade, `AND` may still be overly strict and return `0` hits; consider falling back to `OR` or no operator when `AND` yields empty results.

---

## 10) Running the AI server

After configuring your `.env`, start the backend server with:

```bash
python start_AI_server.py --env
```

### Endpoint modes (`developement` / `APP_DEVELOPMENT`)

`config.json`:
- set `"developement": true` to expose development endpoints
- set `"developement": false` to hide development endpoints

Override via env:
- `APP_DEVELOPMENT=1` enables dev endpoints
- `APP_DEVELOPMENT=0` hides dev endpoints (`404`)

Development endpoints:
- `GET /app-config/dev`
- `POST /search/dev`, `POST /query/dev`

Production endpoints (always bearer-protected):
- `GET /app-config/prod`
- `POST /search/prod`, `POST /query/prod`

Auth behavior for `prod` endpoints:
- if IDP config is active, bearer is validated as JWT (issuer/audience/JWKS)
- otherwise fallback is exact match `Authorization: Bearer <API_TOKEN>`
- after bearer validation, server enforces custom access checks:
  - user must be allowed to run the selected pipeline
  - when `snapshot_set_id` + snapshot ids are provided, each snapshot must belong to that set
    - primary: `snapshot_id`
    - secondary (compare): `snapshot_id_b`

Security incident logging:
- rejected auth/authorization attempts are logged with tag `[security_abuse]`
---

## 11) Notes for production

* Use a **production WSGI server** (e.g., Gunicorn/uWSGI) instead of the Flask dev server (`flask run`). Disable debug, load environment variables via `python-dotenv` if needed, and place a reverse proxy (Nginx/Traefik) in front for TLS and compression.
* **Model integrity (checksums):** always verify the SHA‑256 of downloaded weights before startup.

  ```bash
  # Generate checksums after download (commit this file to the repo if you want reproducibility)
  (cd code_analysis/codeLlama_13b_Instruct && sha256sum *.gguf > CHECKSUMS.sha256)
  (cd embedding && find . -type f ! -name 'download_model.md' -maxdepth 1 -print0 | xargs -0 sha256sum > CHECKSUMS.sha256)
  (cd translation/en_pl/Helsinki_NLPopus_mt_en_pl && sha256sum * > CHECKSUMS.sha256)
  (cd translation/pl_en/Helsinki-NLPopus-mt-pl-en && sha256sum * > CHECKSUMS.sha256)

  # Verify at deploy/start time
  sha256sum -c code_analysis/codeLlama_13b_Instruct/CHECKSUMS.sha256
  sha256sum -c embedding/CHECKSUMS.sha256
  sha256sum -c translation/en_pl/Helsinki_NLPopus_mt_en_pl/CHECKSUMS.sha256
  sha256sum -c translation/pl_en/Helsinki-NLPopus-mt-pl-en/CHECKSUMS.sha256
  ```

  If you prefer, store expected digests in `checksums.json` and verify them in an app startup hook.
* **Deployment hygiene (remove MD placeholders):** production artifacts/images should ship only the code and the weights. Remove the `download_model.md` files during packaging to avoid leaking internal instructions:

  ```bash
  find code_analysis embedding translation -name 'download_model.md' -delete
  ```
* **GPU concurrency:** for a single GPU, prefer **one process/worker** to avoid loading the model multiple times into VRAM; scale with a queue or per‑GPU processes when needed.
* **Observability:** expose `/healthz` and `/readyz`, emit structured logs (JSON), and add latency/throughput metrics for retrieval and generation stages.

---

## 12) Frontend example (RAG.html)

The `frontend/` folder contains a **sample web interface** `RAG.html`  
that lets you query the AI system directly from your browser.

It is a standalone, dependency-free HTML file built with **TailwindCSS**, **Highlight.js**, and **Marked.js** for Markdown rendering.  
You can open it locally after starting the server (`python start_AI_server.py --env`),  
and it will connect to `http://localhost:5000` for backend communication.

This frontend was created specifically for extensibility —  
future versions may include advanced features such as **repository comparison**, **branch diffs**, or **multi-repo queries**.

### Frontend Development Notes

The frontend (`frontend/RAG.html`) is currently a **single-file implementation** for ease of development and testing. It includes inline CSS, JavaScript, and dependencies loaded via CDNs (e.g., TailwindCSS, Highlight.js, Marked.js). This setup allows quick iteration and local testing without build tools, but it is **not production-ready**. For deployment in a production environment, perform the following steps to optimize, secure, and maintain the code:

1. **Separate assets:** Extract inline CSS and JS into separate files (e.g., `styles.css`, `script.js`) for better organization and caching.

2. **Use a bundler:** Integrate a tool like Vite, Parcel, or Webpack to minify assets, bundle dependencies, and eliminate CDNs. This reduces load times and avoids external dependencies.
   - Example: Set up Vite with `vite.config.js` for Tailwind PostCSS integration.

3. **Update dependencies:** Replace outdated CDN versions (e.g., Tailwind 2.2.19, Highlight.js 11.7.0) with the latest stable releases (e.g., Tailwind 3.4+, Highlight.js 11.10+). Use npm/yarn for local installs.

4. **Add security headers:** Implement Content Security Policy (CSP) to restrict script sources. Avoid inline styles/scripts in production to mitigate XSS risks.

5. **Optimize for production:** Remove development-only elements (e.g., debug badges, console logs). Add error handling, accessibility (ARIA attributes), and responsive testing.

6. **Deployment:** Serve via a static file server (e.g., Nginx) with HTTPS. If scaling, consider integrating with a framework like React for more complex features.

Once these changes are applied, the frontend can be treated as production code. For now, open `RAG.html` directly in your browser after starting the backend server.

---
# 13) Integration: PlantUML (UML Diagrams)

* **Run the local server (Docker):**

  ```bash
  docker run -d --name plantuml -p 8080:8080 plantuml/plantuml-server
  ```

  Health check: `curl http://localhost:8080/` → should return HTML.

* **Point RAG to the server:** add to `config.json`

  ```json
  "plantuml_server": "http://localhost:8080"
  ```

* **How it’s used:** when the **Ada Lovelace** diagrammer is selected, the system generates `.puml` files **and** an **Open UML Diagram** link that renders through your PlantUML server. If the server isn’t running or the URL is wrong, the link won’t render.

* **Notes/Troubleshooting:**

  * Change the URL if your server runs elsewhere (e.g., a VM or remote host).
  * On WSL, `http://localhost:8080` works from Windows if the container publishes to that port.
  * Port already in use? Pick another, e.g.:

    ```bash
    docker run -d --name plantuml -p 8081:8080 plantuml/plantuml-server
    ```

    and set `"plantuml_server": "http://localhost:8081"`.

---

# 14) Quickstart (TL;DR)

> **This section is fully consistent with the README.** It uses the Conda env name from `environment.yml` (**RAG-FAISS2**), installs the correct CUDA wheel of `llama-cpp-python` via a local file with `--no-deps`, downloads models via the one‑shot script first, and then provides verification and server start commands.

---

```bash
# 1) Create & activate env (matches environment.yml)
conda env create -f environment.yml && conda activate rag-weaviate

# 2) Install CUDA wheel of llama-cpp-python (cu121, Python 3.11)
pip uninstall -y llama-cpp-python
wget https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.16-cu121/llama_cpp_python-0.3.16-cp311-cp311-linux_x86_64.whl
pip install --no-deps ./llama_cpp_python-0.3.16-cp311-cp311-linux_x86_64.whl

# (If you get a sacremoses error later)
# pip install sacremoses

# 3) Download all models — one‑shot downloader (recommended)
chmod +x download_models.sh
./download_models.sh

# If anything fails, open each target folder's download_model.md
# and run its copy‑paste commands exactly (no new folders).

# 4) Verify GPU acceleration (after models are present)
python tests/test_llama_gpu.py

# 5) Run the server (env vars from .env)
cp -n .env.example .env 2>/dev/null || true
python start_AI_server.py --env

# Optional: open the sample frontend (connects to http://localhost:5000)
# xdg-open frontend/RAG.html 2>/dev/null || true
```

### Notes

* If FAISS‑GPU is unavailable on your platform/Python, you can temporarily use `faiss-cpu` and proceed.
* If the CUDA wheel doesn’t match your CUDA/Python, pick the appropriate one from the `llama-cpp-python` release page (keep `--no-deps`).
* The downloader writes **only** into the existing directories and Git ignores the fetched weights.
