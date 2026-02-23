# llama.cpp Server (CUDA) on WSL2 + Docker — Step-by-step

This guide describes how to run **llama.cpp HTTP server** (the `llama-server` binary) in Docker on **WSL2 Ubuntu 22.04** with **NVIDIA GPU** acceleration.

**Server name (FYI):**
- Project: **llama.cpp**
- Server binary: **`llama-server`**
- Docker image used here: **`ghcr.io/ggml-org/llama.cpp:server-cuda`**
- API style: **OpenAI-compatible** (`/v1/models`, `/v1/chat/completions`, ...)

---

## 1) Prerequisites

### 1.1 GPU and drivers (WSL2)
In WSL, verify GPU visibility:

```bash
nvidia-smi
```

You should see your GPU eg. RTX 4090 (or other NVIDIA GPU).

### 1.2 Docker engine inside WSL (not Docker Desktop)
Verify Docker is working:

```bash
docker version
docker info | grep -i "Operating System"
```

Expected: `Operating System: Ubuntu 22.04...`

---

## 2) Enable GPU support in Docker (NVIDIA runtime)

The critical requirement is that Docker must expose the **`nvidia`** runtime.

### 2.1 Install NVIDIA Container Toolkit repo + package

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /etc/apt/keyrings/nvidia-container-toolkit.gpg
sudo chmod a+r /etc/apt/keyrings/nvidia-container-toolkit.gpg

distribution=$(. /etc/os-release; echo ${ID}${VERSION_ID})
curl -fsSL https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list   | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia-container-toolkit.gpg] https://#g'   | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
```

### 2.2 Configure Docker runtime

```bash
sudo nvidia-ctk runtime configure --runtime=docker
```

This typically creates/updates:

- `/etc/docker/daemon.json`

### 2.3 Restart Docker

If you have service scripts:

```bash
sudo service docker restart
```

If you use a different init setup, restart `dockerd` in the way your system starts it.

### 2.4 Validate runtime and GPU in container

Check that `nvidia` runtime is present:

```bash
docker info | grep -i runtimes
```

Expected: `... nvidia ...`

Then test GPU in a container:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

---

## 3) Create docker-compose for llama.cpp server-cuda

Recommended folder structure (example):

```
LocalAI-RAG/
  models/
  docker-server-llm/
    docker-compose.yml
```

Example `docker-compose.yml`:

```yaml
services:
  llama_cpp:
    image: ghcr.io/ggml-org/llama.cpp:server-cuda
    ports:
      - "127.0.0.1:18081:8080"
    gpus: all
    volumes:
      - ../models:/models:ro
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    command:
      - "--host"
      - "0.0.0.0"
      - "--port"
      - "8080"
      - "--jinja"
      - "-ngl"
      - "99"
      - "-c"
      - "8192"
      - "-m"
      - "/models/code_analysis/Devstrall-2-24B/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"
```

Notes:
- The `ports` line binds the server to **localhost only** (safer default).
- `gpus: all` enables CUDA access in the container.
- `-ngl 99` attempts to offload all layers (actual is limited by VRAM).
- `-c 8192` sets runtime context length to 8192.
- Model path **must exist** inside mounted `/models`.

---

## 4) Start the server

From the `docker-server-llm` directory:

```bash
docker compose pull
docker compose up -d
```

Follow logs:

```bash
docker logs -f docker-server-llm-llama_cpp-1
```

Good signs in logs:
- `using device CUDA0`
- `offloaded ... layers to GPU`
- `server is listening on http://0.0.0.0:8080`

---

## 5) Test the server (OpenAI-compatible API)

### 5.1 List models
```bash
curl -s http://127.0.0.1:18081/v1/models | head
```

Use the returned model `id` in requests.

### 5.2 Chat completion (non-stream)
```bash
curl -s http://127.0.0.1:18081/v1/chat/completions   -H "Content-Type: application/json"   -d '{
    "model": "Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf",
    "messages": [
      {"role":"system","content":"You are a concise assistant."},
      {"role":"user","content":"Say OK."}
    ],
    "temperature": 0.1,
    "max_tokens": 16
  }'
```

---

## 6) Switching models quickly

### Option A: Change `-m` in docker-compose and recreate container
1) Edit `docker-compose.yml` → update `-m /models/...`.
2) Restart:

```bash
docker compose up -d --force-recreate
```

### Option B: Run a second server on another port
Copy the service with different:
- `ports` mapping (e.g., `127.0.0.1:18082:8080`)
- `-m` model path

---

# Troubleshooting (big section)

## A) `could not select device driver "" with capabilities: [[gpu]]`
Cause: Docker has no NVIDIA runtime.

Fix checklist:
1) `docker info | grep -i runtimes` must include `nvidia`.
2) Install toolkit + configure runtime:

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo service docker restart
```

3) Validate GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

## B) `nvidia-ctk: command not found`
Cause: toolkit not installed or repo missing.

Fix: add NVIDIA repo and install `nvidia-container-toolkit` (see section 2.1).

## C) Container starts but server not reachable
Check:
- Port mapping: `127.0.0.1:18081:8080`
- Container running:

```bash
docker ps
```

- Server logs:

```bash
docker logs docker-server-llm-llama_cpp-1 | tail -n 80
```

If you mapped to localhost only, access must be from the same machine/WSL context:
- URL: `http://127.0.0.1:18081`

## D) Model path not found
Log usually shows file-not-found.

Verify host path exists:

```bash
ls -lh ../models/code_analysis/Devstrall-2-24B/*.gguf
```

Verify container sees it:

```bash
docker exec -it docker-server-llm-llama_cpp-1 ls -lh /models/code_analysis/Devstrall-2-24B/
```

## E) GPU memory / OOM issues
Symptoms:
- model fails to load
- partial offload
- CUDA allocation errors

Fixes:
- Reduce context length (`-c 4096`)
- Reduce `-ngl` (e.g. `-ngl 60`)
- Close other GPU consumers
- Use smaller quant (Q4 instead of Q6/Q8) or smaller model

## F) Slow generation
Common causes:
- running on CPU (check logs for CUDA)
- too large context
- low batch settings

Check logs for:
- `using device CUDA0`
- `offloaded ... layers to GPU`

Consider:
- Lower `-c`
- Ensure `gpus: all` and NVIDIA runtime is active

## G) Warnings about tokenizer / EOS / EOG
Example:
- `special_eos_id is not in special_eog_ids`

Usually non-fatal. If stopping behaves badly:
- Use explicit `stop` sequences in client requests.
- Prefer `/v1/chat/completions` with proper `messages`.

## H) Docker CLI spam: “Plugin ... is not valid”
This is noisy but typically harmless.

To remove broken symlinks (safe):

```bash
sudo find /usr/local/lib/docker/cli-plugins -type l -xtype l -delete
```

## I) Port already in use
If `18081` is taken:
- change to another host port (e.g., `18082:8080`)
- restart compose.

## J) Binding to LAN (not recommended by default)
If you change port mapping to `0.0.0.0:18081:8080`, the service becomes reachable from the network.
If you do that:
- add firewall rules
- add authentication/reverse proxy (nginx) and TLS
- consider IP allowlists

---

## Operational tips

### Logs
```bash
docker logs -f docker-server-llm-llama_cpp-1
```

### Stop / start
```bash
docker compose down
docker compose up -d
```

### Update image
```bash
docker compose pull
docker compose up -d
```
