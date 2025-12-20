# File: vector_db/build_unified_index.py

"""
===============================================
🔹 Unified Index Builder (FAISS + TF/BM25-ready) (C# + SQL + multi-branch)
===============================================

Repo layout (required):
repositories/
  <projectName>/
    branches/   # source ZIPs + extracted branch folders
    indexes/    # output indexes (FAISS + TF + metadata + manifest)

What it builds (inside indexes/<IndexId>/):
- unified_index.faiss
- unified_metadata.json
- TF/BM25-ready artifacts (no pickle):
  tf_vocab.json, tf_offsets.npy, tf_doc_ids.npy, tf_tfs.npy, tf_df.npy, tf_doc_len.npy, tf_index_meta.json
- manifest.json (exact ZIPs used + sha256)

IndexId:
- YYYY-MM-DD__<friendly_slug>  e.g. 2025-12-22__stable+dev
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
import re
import hashlib
from datetime import datetime
from typing import Any, Dict, List

import faiss
import torch
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer

# Reuse helpers for config / paths from the existing builder
from vector_db.build_vector_index import load_config, resolve_path, human_size, extract_to_named_root

# Reuse helpers for reading C# and SQL artifacts
from vector_db.build_cs_index import find_chunks_json, clean_text as clean_cs_text
from vector_db.build_sql_index import (
    find_sql_bodies_jsonl,
    load_edges,
    format_relations_block,
    split_into_chunks,
    clean_text as clean_sql_text,
)

# TF index (BM25-ready, no pickle)
from vector_db.tf_index import build_tf_index


# ======================================
# 🔹 Path helpers
# ======================================

_SLUG_ALLOWED = re.compile(r"[^a-z0-9+\-_]+")


def _join_under(base_dir: str, maybe_rel: str) -> str:
    """If maybe_rel is absolute -> return it, otherwise join under base_dir."""
    if not maybe_rel:
        return base_dir
    return maybe_rel if os.path.isabs(maybe_rel) else os.path.join(base_dir, maybe_rel)


def slugify_friendly_name(name: str) -> str:
    """
    Convert a friendly name into a filesystem-friendly slug.
    Keeps: a-z, 0-9, '+', '-', '_'
    Converts spaces and separators to '+' and collapses duplicates.
    """
    s = (name or "").strip().lower()
    if not s:
        return "index"

    s = re.sub(r"[\s/\\|,;:]+", "+", s)
    s = _SLUG_ALLOWED.sub("", s)
    s = re.sub(r"\++", "+", s).strip("+")
    return s or "index"


def sha256_of_file(path: str) -> str:
    """Compute SHA256 of a file in a streaming way."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    """Collect C# (regular code) documents for unified indexing."""
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

        if entry_id:
            doc_id = str(entry_id)
        else:
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
    """Collect SQL (db_code) documents for unified indexing."""
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
                continue

            header = make_header(kind, schema, name, file_path, key)
            full_text = f"{header}\n---\n{body}".strip()

            chunks = split_into_chunks(full_text, max_chars=4000)
            for chunk_text, part, parts in chunks:
                meta: Dict[str, Any] = {
                    "id": f"{key}:part={part}",
                    "data_type": "db_code",
                    "file_type": "sql",
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
# 🔹 Unified FAISS + TF builder
# ======================================

def build_unified_index(index_id: str | None = None) -> None:
    """
    Build unified FAISS index + TF (BM25-ready) index for one or more branches.

    Target layout:
      repositories/<repo_name>/branches
      repositories/<repo_name>/indexes/<IndexId>
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config, config_dir = load_config(script_dir)

    repo_name = config.get("repo_name", "project")

    # repositories root (relative to config.json)
    repositories_root = resolve_path(config.get("repositories_root", "repositories"), config_dir)
    project_root = os.path.join(repositories_root, repo_name)

    branches_dir = _join_under(project_root, config.get("branches_dir", "branches"))
    indexes_root = _join_under(project_root, config.get("indexes_root", "indexes"))

    os.makedirs(branches_dir, exist_ok=True)
    os.makedirs(indexes_root, exist_ok=True)

    print(f"\n📁 Project root:    {project_root}")
    print(f"📁 Branches dir:    {branches_dir}")
    print(f"📁 Indexes root:    {indexes_root}")
    print(f"🏷️  Repo name:       {repo_name}")

    # 1) Choose archives
    zip_files = list_archives(branches_dir)
    if not zip_files:
        print("\n❌ No ZIP archives found in branches directory.")
        return

    chosen_zips = choose_archives(zip_files)
    print("\n🧩 Selected archives:")
    for z in chosen_zips:
        print(f"   - {os.path.basename(z)}")

    # 2) Determine IndexId + FriendlyName
    friendly_default = "+".join(os.path.splitext(os.path.basename(z))[0] for z in chosen_zips)
    if index_id is None:
        friendly = input(f"\nFriendlyName for this index (Enter = {friendly_default}): ").strip()
        if not friendly:
            friendly = friendly_default

        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = slugify_friendly_name(friendly)
        index_id = f"{date_str}__{slug}"
    else:
        friendly = index_id

    index_dir = os.path.join(indexes_root, index_id)
    os.makedirs(index_dir, exist_ok=True)

    print(f"🏷️  Index ID:        {index_id}")
    print(f"📁 Index directory: {index_dir}")

    # 3) Collect documents from all selected branches
    all_docs: List[Dict[str, Any]] = []

    for zip_path in chosen_zips:
        zip_base = os.path.splitext(os.path.basename(zip_path))[0]
        branch_name = zip_base

        print(f"\n📦 Extracting {os.path.basename(zip_path)} → {branches_dir}")
        branch_root = extract_to_named_root(zip_path, branches_dir)
        print(f"✅ Using branch_root: {branch_root}")

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

    # 4) TF index (BM25-ready, no pickle)
    print("\n🏗️  Building TF index (BM25-ready, no pickle)…")
    build_tf_index(texts, index_dir)
    print("✅ TF index artifacts saved.")

    # 5) FAISS embeddings
    model_path = resolve_path(config["model_path_embd"], config_dir)
    print(f"\n🔧 Embedding model: {model_path}")

    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    device = torch.device("cuda" if torch.cuda.is_available() and config.get("use_gpu", True) else "cpu")
    print(f"✅ Using device: {device}")
    gpu_available = device.type == "cuda"
    res = faiss.StandardGpuResources() if gpu_available else None

    embedding_model = SentenceTransformer(model_path).to(device)

    print("\n🏗️  Generating embeddings for unified FAISS index…")
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

    index = faiss.IndexFlatIP(dimension)
    if gpu_available:
        index = faiss.index_cpu_to_gpu(res, 0, index)
    index.add(vectors_np)

    # 6) Save FAISS and metadata
    faiss_path = os.path.join(index_dir, "unified_index.faiss")
    meta_path = os.path.join(index_dir, "unified_metadata.json")

    index_to_save = faiss.index_gpu_to_cpu(index) if gpu_available else index
    faiss.write_index(index_to_save, faiss_path)

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # 7) Manifest (exact ZIPs + sha256)
    manifest_path = os.path.join(index_dir, "manifest.json")
    branches_manifest: List[Dict[str, Any]] = []
    for z in chosen_zips:
        branches_manifest.append(
            {
                "zip_file": os.path.basename(z),
                "zip_sha256": sha256_of_file(z),
                "zip_size_bytes": int(os.path.getsize(z)),
                "zip_mtime_utc": datetime.utcfromtimestamp(os.path.getmtime(z)).isoformat(timespec="seconds") + "Z",
                "branch_name": os.path.splitext(os.path.basename(z))[0],
            }
        )

    manifest = {
        "format": "unified_index_manifest_v1",
        "index_id": index_id,
        "friendly_name": friendly,
        "repo_name": repo_name,
        "created_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "branches": branches_manifest,
        "artifacts": {
            "faiss_index": "unified_index.faiss",
            "metadata": "unified_metadata.json",
            "tf_index": [
                "tf_vocab.json",
                "tf_offsets.npy",
                "tf_doc_ids.npy",
                "tf_tfs.npy",
                "tf_df.npy",
                "tf_doc_len.npy",
                "tf_index_meta.json",
            ],
        },
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Unified FAISS index saved to: {faiss_path}")
    print(f"✅ Unified metadata saved to:   {meta_path}")
    print(f"✅ Manifest saved to:           {manifest_path}\n")


def main() -> None:
    # Optional: allow overriding IndexId via CLI
    # python -m vector_db.build_unified_index 2025-12-22__stable+dev
    index_id = sys.argv[1] if len(sys.argv) > 1 else None
    build_unified_index(index_id=index_id)


if __name__ == "__main__":
    main()
