# 🧩 HOW_TO_PREPARE_REPO.md

**Preparing your source repository for RAG analysis**

This guide shows how to **index a .NET + SQL repository** with the external **RoslynIndexer** project and how to **build FAISS vector indexes** consumed by the RAG engine.

Output is a self-contained branch bundle (ZIP) + FAISS indexes ready for semantic search.

---

## 1️⃣ Purpose

The indexer converts your repo into structured artifacts:

| Type                | Description                                                    | Target Folder                            |
| ------------------- | -------------------------------------------------------------- | ---------------------------------------- |
| `chunks.json`       | Extracted C# members (methods, properties, constructors, etc.) | `branches/<branch>/regular_code_bundle/` |
| `dependencies.json` | Dependency graph / references                                  | `branches/<branch>/regular_code_bundle/` |
| `repo_meta.json`    | Metadata (branch, commit, timestamp, paths)                    | `branches/<branch>/`                     |
| `sql_bundle/*`      | Parsed SQL defs + dependency graph                             | `branches/<branch>/sql_bundle/`          |
| `<branch>.zip`      | Final compressed bundle                                        | `branches/`                              |

These artifacts are then embedded into FAISS (GPU-accelerated) for fast search.

---

## 2️⃣ Prerequisites

* **Indexing (Windows):**

  * Windows 10/11 x64
  * **.NET SDK 9.0**
  * Visual Studio 2022 (or Build Tools) with MSBuild components
* **Vector build (Linux/WSL2 or Linux runner):**

  * Conda env **`rag-faiss`** (see `environment.yml`)
  * NVIDIA GPU + drivers (for FAISS-GPU / llama.cpp)

> ℹ️ The .NET indexer lives in a separate repo and **does not compile your solution**; it evaluates MSBuild + parses sources.

---

## 3️⃣ Index your .NET repo (Windows)

Use the external indexer: **[https://github.com/RusieckiRoland/RoslynIndexer.git](https://github.com/RusieckiRoland/RoslynIndexer.git)**
Read its README for advanced configuration (JSON config, MSBuild overrides, TransformXml, etc.).

### PowerShell (typical)

```powershell
git clone https://github.com/RusieckiRoland/RoslynIndexer.git
cd RoslynIndexer

dotnet run --project .\RoslynIndexer.Net9\RoslynIndexer.Net9.csproj -- `
  --solution "D:\Repo\src\MySolution.sln" `
  --temp-root "D:\Work\.idx"
```

If you use a JSON config (recommended), pass `--config "D:\path\config.json"` instead.

**Result:** a ZIP named after the Git branch appears under the configured `out` folder (or local `.artifacts\index`).
Copy that ZIP into **`branches/`** of this repo.

---

## 4️⃣ Build the FAISS vector database

### Activate environment

```bash
conda activate rag-faiss
```

### Interactive mode (default)

```bash
python build_vector_index.py
```

You’ll be asked to pick:

1. a ZIP from `branches/`,
2. what to build: **C#**, **SQL**, or **Both**.

### Non-interactive (CI-friendly) via env vars

* `ZIP_PATH` → which ZIP to use (absolute or under `branches/`)
* `MODE` → `cs` | `sql` | `both` (default)
* `SKIP_CLEAR=1` → don’t clear console (nice for logs)

**Bash / WSL / Linux**

```bash
ZIP_PATH="branches/developement.zip" MODE="both" SKIP_CLEAR=1 \
python build_vector_index.py
```

**PowerShell**

```powershell
$env:ZIP_PATH   = "branches\developement.zip"
$env:MODE       = "both"   # cs | sql | both
$env:SKIP_CLEAR = "1"
python .\build_vector_index.py
```

**Outputs (next to sources):**

```
branches/<branch>/regular_code_bundle/code_index.faiss
branches/<branch>/regular_code_bundle/metadata.json
branches/<branch>/sql_bundle/sql_index.faiss
branches/<branch>/sql_bundle/sql_metadata.json
```

---

## 5️⃣ Verify

```bash
ls -lh branches/<branch>/regular_code_bundle/
ls -lh branches/<branch>/sql_bundle/
```

You should see `.faiss` + `.json` metadata files.

---

## 6️⃣ Launch the RAG backend

```bash
python start_AI_server.py --env
```

Open the sample UI:

```
frontend/RAG.html
```

---

## 7️⃣ CI/CD usage (notes + minimal examples)

The recommended split is:

1. **Windows job:** run **RoslynIndexer** (MSBuild available), publish the resulting ZIP as an artifact.
2. **Linux job (GPU):** download the ZIP artifact to this repo’s `branches/`, then run the vector builder in env **`rag-faiss`** with `ZIP_PATH` + `MODE`.

> Always pass `MODE` explicitly (`cs` / `sql` / `both`) and set `SKIP_CLEAR=1` for clean logs.

### GitHub Actions (minimal pattern)

```yaml
name: Build RAG Indexes

on: [workflow_dispatch]

jobs:
  index-dotnet:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - name: Clone RoslynIndexer
        run: git clone https://github.com/RusieckiRoland/RoslynIndexer.git
      - name: .NET 9
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '9.0.x'
      - name: Run indexer
        working-directory: RoslynIndexer
        run: >
          dotnet run --project .\RoslynIndexer.Net9\RoslynIndexer.Net9.csproj --
          --solution "D:\a\repo\src\MySolution.sln" --temp-root "D:\a\work\.idx"
      - name: Publish ZIP artifact
        uses: actions/upload-artifact@v4
        with:
          name: branch-zip
          path: RoslynIndexer\.artifacts\index\*.zip

  build-vectors:
    needs: index-dotnet
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Download ZIP
        uses: actions/download-artifact@v4
        with:
          name: branch-zip
          path: branches
      - name: Set up Miniconda
        uses: conda-incubator/setup-miniconda@v3
        with:
          activate-environment: rag-faiss
          environment-file: environment.yml
          auto-activate-base: false
      - name: Build FAISS (both)
        env:
          ZIP_PATH: branches/*.zip
          MODE: both
          SKIP_CLEAR: "1"
        run: python build_vector_index.py
```

### Azure DevOps (sketch)

```yaml
trigger: none

stages:
- stage: Index
  jobs:
  - job: index_dotnet
    pool: { vmImage: 'windows-latest' }
    steps:
    - checkout: self
    - powershell: git clone https://github.com/RusieckiRoland/RoslynIndexer.git
    - task: UseDotNet@2
      inputs: { version: '9.x' }
    - powershell: >
        dotnet run --project .\RoslynIndexer\RoslynIndexer.Net9\RoslynIndexer.Net9.csproj --
        --solution "$(Build.SourcesDirectory)\src\MySolution.sln" --temp-root "$(Agent.TempDirectory)\.idx"
    - publish: RoslynIndexer\.artifacts\index
      artifact: branch-zip

- stage: Vectors
  dependsOn: Index
  jobs:
  - job: build_vectors
    pool: { vmImage: 'ubuntu-latest' }
    steps:
    - checkout: self
    - download: current
      artifact: branch-zip
    - task: Bash@3
      inputs:
        targetType: inline
        script: |
          mv "$(Pipeline.Workspace)/branch-zip" branches
          conda env create -f environment.yml || true
          source ~/miniconda/etc/profile.d/conda.sh
          conda activate rag-faiss
          ZIP_PATH="branches/*.zip" MODE="both" SKIP_CLEAR=1 python build_vector_index.py
```

**CI tips:**

* If the ZIP should land on WSL/UNC, configure the indexer `out` path to a shared location, and in the “vectors” job copy the ZIP into `branches/`.
* If you want to build **C#** and **SQL** separately, run two steps with different `MODE` values (e.g., `cs` first, then `sql`).

---

✅ **Result:** the repository is indexed, vectorized, and ready for local, GPU-accelerated RAG — both locally and in CI/CD.
