"""
===============================================
🔹 Unified Vector Index Builder (C# + SQL + multi-branch)
===============================================

Purpose:
- Build ONE unified FAISS index ("unified_index.faiss") plus metadata
  ("unified_metadata.json") from one or more branch archives (ZIPs).
- Combine both regular code (C#) and DB code (SQL) into a single index.

Usage (example):
- python build_unified_index.py

It will:
1) Load config.json (same as build_vector_index.py).
2) Look for branch ZIPs under `output_dir` from config (e.g. ./branches).
3) Let you select one or more archives (comma-separated).
4) Extract each archive into branches/<zipname>/.
5) Collect C# and SQL documents, tagging them with:
   - data_type: "regular_code" or "db_code"
   - file_type: "cs" or "sql" (later you can extend with ef_migration / inline_sql)
   - repo: "nopCommerce" (for now; can be made configurable)
   - branch: <zipname without .zip>
6) Build a unified FAISS index and save it under:
   vector_indexes/<index_id>/unified_index.faiss
   vector_indexes/<index_id>/unified_metadata.json
"""

from __future__ import annotations

import sys
from unittest.mock import Mock

# Avoid optional image deps pulled in by sentence_transformers
sys.modules["transformers.image_utils"] = Mock()
sys.modules["transformers.image_transforms"] = Mock()

import os
import json
import time
import zipfile
from typing import Any, Dict, List

import faiss
import torch
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer

# Reuse helpers for config / paths from the existing builder
from build_vector_index import load_config, resolve_path, human_size, extract_to_named_root

# Reuse helpers for reading C# and SQL artifacts
from vector_db.build_cs_index import find_chunks_json, clean_text as clean_cs_text
from vector_db.build_sql_index import (
    find_sql_bodies_jsonl,
    load_edges,
    format_relations_block,
    split_into_chunks,
    clean_text as clean_sql_text,
)


# ======================================
# 🔹 Archive selection
# ======================================

def list_archives(branches_dir: str) -> List[str]:
    """Return a list of absolute paths to ZIPs under branches_dir, newest first."""
    if not os.path.isdir(branches_dir):
        return []

    zip_files = [
        os.path.join(branches_dir, f)
        for f in os.listdir(branches_dir)
        if f.lower().endswith(".zip") and os.path.isfile(os.path.join(branches_dir, f))
    ]
    zip_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return zip_files


def choose_archives(zip_files_abs: List[str]) -> List[str]:
    """
    Let the user select one or more archives by number.

    Input formats:
      - "" (Enter) -> [first archive]
      - "2"        -> [second archive]
      - "1,3,4"    -> [1st, 3rd, 4th archive]
    """
    if not zip_files_abs:
        return []

    print("\n📦 Available branch archives in 'branches':")
    for i, zabs in enumerate(zip_files_abs, 1):
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(zabs)))
        print(f"  [{i}]{' *' if i == 1 else ''} {os.path.basename(zabs)}  ({human_size(zabs)}, {mtime})")

    sel = input("Select archive numbers (comma-separated, Enter = 1): ").strip()
    if not sel:
        indices = [1]
    else:
        try:
            indices = [int(x.strip()) for x in sel.split(",") if x.strip()]
        except ValueError:
            print("❌ Invalid input. Use numbers like '1' or '1,3,4'.")
            sys.exit(1)

    chosen: List[str] = []
    for idx in indices:
        if idx < 1 or idx > len(zip_files_abs):
            print(f"❌ Invalid selection: {idx}")
            sys.exit(1)
        chosen.append(zip_files_abs[idx - 1])

    return chosen


# ======================================
# 🔹 Document collection
# ======================================

def collect_cs_documents(branch_root: str, repo_name: str, branch_name: str) -> List[Dict[str, Any]]:
    """
    Collect C# (regular code) documents for unified indexing.

    Each returned item has the shape:
      {
        "text": <string>,
        "meta": {
          "id": <stable id>,
          "data_type": "regular_code",
          "file_type": "cs",
          "source_file": ...,
          "chunk_part": 0,
          "chunk_total": 1,
          "class": ...,
          "member": ...,
          "repo": repo_name,
          "branch": branch_name,
          ...
        }
      }
    """
    try:
        chunk_file_path = find_chunks_json(branch_root)
    except FileNotFoundError:
        print(f"⚠️  No chunks.json found under {branch_root} (skipping C#).")
        return []

    with open(chunk_file_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    docs: List[Dict[str, Any]] = []

    for entry in chunks:
        raw_text = entry.get("Text", "") or entry.get("Content", "")
        content = clean_cs_text(raw_text)

        file_path = entry.get("File")
        class_name = entry.get("Class")
        member_name = entry.get("Member")
        entry_id = entry.get("Id")

        # Stable-ish id: prefer existing Id, otherwise fallback
        if entry_id:
            doc_id = str(entry_id)
        else:
            # Fallback: use file + member
            doc_id = f"cs:{file_path}:{class_name}:{member_name}"

        meta: Dict[str, Any] = {
            "id": doc_id,
            "data_type": "regular_code",
            "file_type": "cs",
            "source_file": file_path,
            "chunk_part": 0,
            "chunk_total": 1,
            "class": class_name,
            "member": member_name,
            "repo": repo_name,
            "branch": branch_name,
        }

        docs.append({"text": content, "meta": meta})

    print(f"✅ Collected {len(docs)} C# documents from: {branch_root}")
    return docs


def collect_sql_documents(branch_root: str, repo_name: str, branch_name: str) -> List[Dict[str, Any]]:
    """
    Collect SQL (db_code) documents for unified indexing.

    Each returned item has the shape:
      {
        "text": <string>,
        "meta": {
          "id": "<db_key>:part=<n>",
          "data_type": "db_code",
          "file_type": "sql",
          "source_file": ...,
          "chunk_part": <int>,
          "chunk_total": <int>,
          "kind": ...,
          "schema": ...,
          "name": ...,
          "db_key": ...,
          "repo": repo_name,
          "branch": branch_name,
          ...
        }
      }
    """
    try:
        bodies_path, _out_dir, edges_csv_path = find_sql_bodies_jsonl(branch_root)
    except FileNotFoundError:
        print(f"⚠️  No sql_bodies.jsonl found under {branch_root} (skipping SQL).")
        return []

    edges_out, ef_refs_to = load_edges(edges_csv_path)

    def make_header(kind: str, schema: str, name: str, file_path: str, key: str) -> str:
        header_lines = [f"[{kind}] {schema}.{name}", f"file: {file_path}"]
        rel_block = format_relations_block(key, edges_out, ef_refs_to)
        if rel_block:
            header_lines.append(rel_block)
        return "\n".join(header_lines)

    docs: List[Dict[str, Any]] = []
    total_chunks = 0

    with open(bodies_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            key = obj.get("key") or obj.get("Key")
            kind = obj.get("kind") or obj.get("Kind") or "Object"
            schema = obj.get("schema") or obj.get("Schema") or "dbo"
            name = obj.get("name") or obj.get("Name") or "Unknown"
            file_path = obj.get("file") or obj.get("File") or ""
            body = obj.get("body") or obj.get("Body") or ""
            body = clean_sql_text(body)

            if not key:
                # Skip malformed records that have no key
                continue

            header = make_header(kind, schema, name, file_path, key)
            full_text = f"{header}\n---\n{body}".strip()

            chunks = split_into_chunks(full_text, max_chars=4000)
            chunk_total = len(chunks)

            for chunk_text, part, parts in chunks:
                # parts should be equal to chunk_total, but we trust split_into_chunks
                meta: Dict[str, Any] = {
                    "id": f"{key}:part={part}",
                    "data_type": "db_code",
                    "file_type": "sql",  # may evolve to ef_migration / inline_sql in the future
                    "source_file": file_path,
                    "chunk_part": part,
                    "chunk_total": parts,
                    "kind": kind,
                    "schema": schema,
                    "name": name,
                    "db_key": key,
                    "repo": repo_name,
                    "branch": branch_name,
                }
                docs.append({"text": chunk_text, "meta": meta})
                total_chunks += 1

    print(f"✅ Collected {total_chunks} SQL document chunks from: {branch_root}")
    return docs


# ======================================
# 🔹 Unified FAISS builder
# ======================================

def build_unified_index(index_id: str | None = None) -> None:
    """
    Build a unified FAISS index for one or more branches.

    - Reads config.json via build_vector_index.load_config.
    - Uses config["output_dir"] as branches directory (same as build_vector_index).
    - Uses config["vector_indexes_root"] (if present) or 'vector_indexes' as root for FAISS artifacts.
    - Uses config["active_index_id"] as default index_id if not provided.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config, config_dir = load_config(script_dir)

    # Where branch ZIPs live (default: ./branches relative to config.json)
    branches_dir = resolve_path(config.get("output_dir", "branches"), config_dir)
    os.makedirs(branches_dir, exist_ok=True)

    # Where FAISS indexes live
    vector_root = resolve_path(config.get("vector_indexes_root", "vector_indexes"), config_dir)
    os.makedirs(vector_root, exist_ok=True)

    # Logical name of this index (used as folder name under vector_root)
    if index_id is None:
        index_id = config.get("active_index_id", "nop_main_index")

    index_dir = os.path.join(vector_root, index_id)
    os.makedirs(index_dir, exist_ok=True)

    # Repository label (for now assume nopCommerce; can be made configurable later)
    repo_name = config.get("repo_name", "nopCommerce")

    print(f"\n📁 Branches dir:    {branches_dir}")
    print(f"📁 Vector root:     {vector_root}")
    print(f"📁 Index directory: {index_dir}")
    print(f"🏷️  Repo name:       {repo_name}")
    print(f"🏷️  Index ID:        {index_id}")

    # 1) Choose archives
    zip_files = list_archives(branches_dir)
    if not zip_files:
        print("\n❌ No ZIP archives found in branches directory.")
        return

    chosen_zips = choose_archives(zip_files)
    print("\n🧩 Selected archives:")
    for z in chosen_zips:
        print(f"   - {os.path.basename(z)}")

    # 2) Collect documents from all selected branches
    all_docs: List[Dict[str, Any]] = []

    for zip_path in chosen_zips:
        zip_base = os.path.splitext(os.path.basename(zip_path))[0]
        branch_name = zip_base

        print(f"\n📦 Extracting {os.path.basename(zip_path)} → {branches_dir}")
        branch_root = extract_to_named_root(zip_path, branches_dir)
        print(f"✅ Using branch_root: {branch_root}")

        # Collect C# and SQL docs for this branch
        cs_docs = collect_cs_documents(branch_root, repo_name=repo_name, branch_name=branch_name)
        sql_docs = collect_sql_documents(branch_root, repo_name=repo_name, branch_name=branch_name)

        all_docs.extend(cs_docs)
        all_docs.extend(sql_docs)

    if not all_docs:
        print("\n⚠️  No documents collected from the selected branches. Nothing to index.")
        return

    texts = [d["text"] for d in all_docs]
    metadata = [d["meta"] for d in all_docs]

    print(f"\n✅ Total documents to index: {len(texts)}")

    # 3) Build embeddings
    model_path = resolve_path(config["model_path_embd"], config_dir)
    print(f"\n🔧 Embedding model: {model_path}")

    # Device selection
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    device = torch.device("cuda" if torch.cuda.is_available() and config.get("use_gpu", True) else "cpu")
    print(f"✅ Using device: {device}")
    gpu_available = device.type == "cuda"
    res = faiss.StandardGpuResources() if gpu_available else None

    embedding_model = SentenceTransformer(model_path).to(device)

    print(f"\n🏗️  Generating embeddings for unified index…")
    vectors: List[np.ndarray] = []
    batch_size = 512
    step = 1000

    for i in tqdm(range(0, len(texts), step), desc="🏗️  Batches"):
        batch = texts[i:i + step]
        batch_vectors = embedding_model.encode(batch, batch_size=batch_size, convert_to_numpy=True)
        vectors.extend(batch_vectors)
        if gpu_available:
            torch.cuda.empty_cache()

    vectors_np = np.array(vectors, dtype="float32")
    faiss.normalize_L2(vectors_np)
    dimension = vectors_np.shape[1]

    # 4) Build FAISS index
    index = faiss.IndexFlatIP(dimension)
    if gpu_available:
        index = faiss.index_cpu_to_gpu(res, 0, index)
    index.add(vectors_np)

    # 5) Save FAISS and metadata
    faiss_path = os.path.join(index_dir, "unified_index.faiss")
    meta_path = os.path.join(index_dir, "unified_metadata.json")

    index_to_save = faiss.index_gpu_to_cpu(index) if gpu_available else index
    faiss.write_index(index_to_save, faiss_path)

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Unified FAISS index saved to: {faiss_path}")
    print(f"✅ Unified metadata saved to:   {meta_path}\n")


def main() -> None:
    # Optional: allow overriding index_id via CLI, e.g.:
    #   python build_unified_index.py nop_main_index
    index_id = sys.argv[1] if len(sys.argv) > 1 else None
    build_unified_index(index_id=index_id)


if __name__ == "__main__":
    main()
