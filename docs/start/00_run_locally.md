# Run locally (end-to-end)

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

---

## 3) .NET indexing (optional)

If you want code-aware retrieval from a .NET + SQL corpus, follow the indexing guide here:

- `docs/start/10_indexing_dotnet_sql.md`

---

## 4) Create the environment

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
```

> ⚙️ **Note:**  
> The `environment.yml` shown above is **for reference only**.  
> It is meant to illustrate the key dependencies but may become outdated as the project evolves.  
> Always use and update the **actual `environment.yml` file** in the repository when creating or updating your Conda environment.

---

## 5) Install `llama-cpp-python` (CUDA build)

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

## 6) Download models into the **existing** folders

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
ls -lh models/code_analysis/*/*.gguf
ls -1  models/embedding/e5-base-v2 | wc -l
ls -1  models/translation/en_pl/Helsinki_NLPopus_mt_en_pl
ls -1  models/translation/pl_en/Helsinki_NLPopus_mt_pl_en
```

If any folder lacks files, use the fallback below.

---

### Fallback: per‑folder `download_model.md`

If something fails, or links change upstream, open the `download_model.md` located **inside each target folder** and execute its **copy‑paste commands** (run them from the **repo root**, do **not** create new directories):

* `models/code_analysis/<model_folder>/download_model.md` → **code model (GGUF, if present)**
* `models/embedding/e5-base-v2/download_model.md` → **embedding model**
* `models/translation/en_pl/Helsinki_NLPopus_mt_en_pl/download_model.md` → **EN→PL** translation
* `models/translation/pl_en/Helsinki_NLPopus_mt_pl_en/download_model.md` → **PL→EN** translation

> **Do not duplicate instructions in the README.** Use the commands from the `download_model.md` files **as‑is**, and place files only into the **existing** directories.

Git tracks **only** the `download_model.md` placeholders; all downloaded weights remain untracked.

Ensure `config.json["model_path_analysis"]` points to the GGUF you downloaded.

**Do not proceed to tests until all four folders contain the downloaded files.**

---

## 7) Configuration files

### `config.json`

```json
{
  "output_dir": "branches",
  "model_path_embd": "models/embedding/e5-base-v2",
  "model_path_analysis": "models/code_analysis/qwenCoder/qwen2.5-coder-32b-instruct-q4_k_m.gguf",
  "model_translation_en_pl": "models/translation/en_pl/Helsinki_NLPopus_mt_en_pl",
  "model_translation_pl_en": "models/translation/pl_en/Helsinki_NLPopus_mt_pl_en",
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

# === Server settings ===
APP_HOST=0.0.0.0
APP_PORT=5000

# === CORS / Origins ===
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080

# === Query limits (optional) ===
APP_MAX_QUERY_LEN=8000
APP_MAX_FIELD_LEN=128

# === Only for debugging the pipeline; creates one JSON per user query
RAG_PIPELINE_TRACE_FILE=1
RAG_PIPELINE_TRACE_DIR=log/pipeline_traces

# === Weaviate (secrets) ===
WEAVIATE_API_KEY=your-weaviate-api-key-here
```

**Description:**

* `APP_SECRET_KEY` — Flask session secret; use a long random string in production.
* `API_TOKEN` — internal API token for service-to-service calls.
* `APP_HOST` / `APP_PORT` — bind address and port of the Flask app.
* `ALLOWED_ORIGINS` — comma-separated list of allowed CORS origins.
* `APP_MAX_QUERY_LEN` / `APP_MAX_FIELD_LEN` — optional server-side limits for incoming requests.
* `RAG_PIPELINE_TRACE_FILE` / `RAG_PIPELINE_TRACE_DIR` — optional per-query trace output (debug only).
* `WEAVIATE_API_KEY` — API key used by Weaviate clients (if your Weaviate is secured).

### OIDC resource server settings in `config.json`

`prod` auth can validate JWT tokens against your Identity Provider (OIDC):

```json
"auth": {
  "oidc": {
    "enabled": true,
    "issuer": "https://idp.example.com/realms/localai-rag",
    "resource_server": {
      "enabled": true,
      "jwks_url": "https://idp.example.com/realms/localai-rag/protocol/openid-connect/certs",
      "audience": "localai-rag-api",
      "algorithms": ["RS256"],
      "required_claims": ["sub", "exp", "iss", "aud"]
    }
  }
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

## 8) Weaviate local setup

Weaviate setup is documented in a separate file:

- `docs/weaviate/weaviate_local_setup.md`

---

## 9) Verify GPU acceleration (**run after models are in place**)

### A) LLaMA (llama‑cpp‑python)

Run this **one‑liner quick test** (copy‑paste) **after Step 5**. It auto‑detects the model under `code_analysis/...` or `models/code_analysis/...`, loads with full CUDA offload, and prints a clear success message in English. **Copy‑paste safe — no unfinished strings.**

```bash
conda activate rag-weaviate
python - <<'PY'
import glob, os, sys, time
from llama_cpp import Llama

print("CWD:", os.getcwd())

patterns = [
    "code_analysis/**/*.gguf",
    "models/code_analysis/**/*.gguf",
    "RAG/code_analysis/**/*.gguf",
    "RAG/models/code_analysis/**/*.gguf",
    "**/*.gguf",  # fallback (recursive)
]
matches = []
for pat in patterns:
    matches.extend(glob.glob(pat, recursive=True))

matches = sorted(set(matches))
if not matches:
    sys.exit(
        "ERROR: no .gguf found. Expected under one of:\n"
        "  - code_analysis/<model_folder>/\n"
        "  - models/code_analysis/<model_folder>/\n"
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

## 10) Typical project layout (models section)

```
models/
├─ code_analysis/
│  └─ <model_folder>/
│     ├─ <your_code_model>.gguf                 # (ignored by Git)
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
      └─ Helsinki_NLPopus_mt_pl_en/
         ├─ [MarianMT files: config.json, *.bin, *.safetensors, sentencepiece.model]  # (ignored by Git)
         └─ download_model.md                   # tracked

```

---

## 11) Running the AI server

After configuring your `.env`, start the backend server with:

```bash
python start_AI_server.py --env
```

### Endpoint surface and auth

The server exposes a single set of endpoints:
- `GET /app-config`
- `POST /search`, `POST /query`
- `GET /pipeline/stream`, `POST /pipeline/cancel`
- `GET /auth-check`

Bearer requirement depends only on `DEV_ALLOW_NO_AUTH`:
- When `DEV_ALLOW_NO_AUTH=true` and `APP_PROFILE!=prod`, the server does not require a real security token, but it still requires a fake login header: `Authorization: Bearer dev-user:<user_id>`.
- In all other cases, bearer validation is required.
- If `APP_PROFILE` is not set, it defaults to `prod`.

Runtime config file is selected by `APP_PROFILE`:
- `APP_PROFILE=dev` uses `config.dev.json`
- `APP_PROFILE=prod` uses `config.prod.json`
- `APP_PROFILE=test` uses `config.test.json`

Auth behavior when bearer is required:
- if IDP config is active, bearer is validated as JWT (issuer/audience/JWKS)

Keycloak-specific setup (PKCE + audience mapper):
- `docs/howto/keycloak_oidc_pkce_setup.md`
- otherwise an optional `API_TOKEN` may be used for **service-to-service** calls only (restricted network); it is not suitable for browser/SPA clients
- after bearer validation, server enforces custom access checks:
  - user must be allowed to run the selected pipeline
  - when `snapshot_set_id` + snapshot ids are provided, each snapshot must belong to that set
    - primary: `snapshot_id`
    - secondary (compare): `snapshot_id_b`

Security incident logging:
- rejected auth/authorization attempts are logged with tag `[security_abuse]`

---

## 12) Open the sample frontend

The `frontend/` folder contains a **sample web interface** `RAG.html`  
that lets you query the AI system directly from your browser.

It is a standalone, dependency-free HTML file built with **TailwindCSS**, **Highlight.js**, and **Marked.js** for Markdown rendering.  
You can open it locally after starting the server (`python start_AI_server.py --env`),  
and it will connect to `http://localhost:5000` for backend communication.

This frontend was created specifically for extensibility —  
future versions may include advanced features such as **repository comparison**, **branch diffs**, or **multi-repo queries**.

---

## 13) Quickstart (TL;DR)

> **This section is fully consistent with the README.** It uses the Conda env name from `environment.yml` (**rag-weaviate**), installs the correct CUDA wheel of `llama-cpp-python` via a local file with `--no-deps`, downloads models via the one‑shot script first, and then provides verification and server start commands.

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
python dev_tools/test_llama_gpu.py
```
