# NOTE: This module exposes build_cs_index(branch_root=None, branch_zip=None)
# - If branch_root is provided: uses it directly (no ZIP selection, no extraction).
# - Else if branch_zip is provided: extracts it and uses the resulting folder.
# - Else: runs in interactive mode (lists ZIPs and asks the user).
#
# Logging file: vector_build.log

import sys
from unittest.mock import Mock
sys.modules["transformers.image_utils"] = Mock()
sys.modules["transformers.image_transforms"] = Mock()

import os
import re
import faiss
import torch
import numpy as np
import json
import time
import logging
import zipfile
from tqdm import tqdm
from sentence_transformers import SentenceTransformer


# ===============================
# 🔹 Helpers
# ===============================
def human_size(path):
    try:
        b = os.path.getsize(path)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024:
                return f"{b:.0f}{unit}"
            b /= 1024.0
        return f"{b:.0f}PB"
    except Exception:
        return "?"


def top_level_in_zip(zip_path):
    with zipfile.ZipFile(zip_path, "r") as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if not names:
            return os.path.splitext(os.path.basename(zip_path))[0]
        roots = {n.split("/", 1)[0] for n in names if "/" in n}
        return list(roots)[0] if len(roots) == 1 else os.path.splitext(os.path.basename(zip_path))[0]


def clean_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def find_chunks_json(branch_root: str) -> str:
    """Find chunks.json within branch_root. Preference: regular_code_bundle/ → code/ → first found anywhere."""
    candidates = [
        os.path.join(branch_root, "regular_code_bundle", "chunks.json"),
        os.path.join(branch_root, "code", "chunks.json"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    for root, _dirs, files in os.walk(branch_root):
        if "chunks.json" in files:
            return os.path.join(root, "chunks.json")
    raise FileNotFoundError("chunks.json not found under " + branch_root)


# ===============================
# 🔹 Public API
# ===============================
def build_cs_index(branch_root: str | None = None, branch_zip: str | None = None):
    """
    Build FAISS index for C# code chunks.

    Args:
        branch_root: Absolute path to the extracted branch folder. If provided, no ZIP selection/extraction occurs.
        branch_zip:  Absolute path to a branch ZIP to extract and use (ignored if branch_root is given).
    """
    # --- Config & logging ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "..", "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    branches_dir = os.path.normpath(config.get("branches_dir", os.path.join(script_dir, "..", "branches")))
    model_path = os.path.join(script_dir, "..", config["model_path_embd"])

    logging.basicConfig(filename="vector_build.log", level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    os.makedirs(branches_dir, exist_ok=True)

    # --- Determine branch_root (priority: explicit branch_root → branch_zip → interactive) ---
    if branch_root and os.path.isdir(branch_root):
        print(f"\n📂 Using provided branch_root: {branch_root}")
    else:
        if branch_zip and os.path.isfile(branch_zip):
            print(f"\n🧩 Extracting provided archive: {os.path.basename(branch_zip)} → {branches_dir}")
            with zipfile.ZipFile(branch_zip, "r") as z:
                z.extractall(branches_dir)
            root_name = top_level_in_zip(branch_zip)
            branch_root = os.path.join(branches_dir, root_name)
            print(f"✅ Extracted to: {branch_root}")
        else:
            # Interactive ZIP selection
            zip_files = [os.path.join(branches_dir, f) for f in os.listdir(branches_dir)
                         if f.lower().endswith(".zip") and os.path.isfile(os.path.join(branches_dir, f))]
            zip_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)

            if zip_files:
                print("\n📦 Found archives in 'branches':")
                for i, z in enumerate(zip_files, 1):
                    star = " *" if i == 1 else ""
                    mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(z)))
                    print(f"  [{i}]{star} {os.path.basename(z)}  ({human_size(z)}, {mtime})")
                sel = input("Select archive number (Enter = 1): ").strip()
                sel_idx = 1 if not sel else int(sel)
                if sel_idx < 1 or sel_idx > len(zip_files):
                    print("❌ Invalid selection."); sys.exit(1)
                chosen_zip = zip_files[sel_idx - 1]
                print(f"🧩 Extracting {os.path.basename(chosen_zip)} → {branches_dir}")
                with zipfile.ZipFile(chosen_zip, "r") as z:
                    z.extractall(branches_dir)
                root_name = top_level_in_zip(chosen_zip)
                branch_root = os.path.join(branches_dir, root_name)
                print(f"✅ Extracted to: {branch_root}")
            else:
                print("\n( No ZIPs in 'branches' )")
                branch = input("🔹 Enter branch folder name (Enter to abort): ").strip()
                if not branch:
                    print("❌ No selection."); sys.exit(1)
                branch_root = os.path.join(branches_dir, branch)
                if not os.path.isdir(branch_root):
                    print(f"❌ Folder does not exist: {branch_root}"); sys.exit(1)

    # --- Device & model ---
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"✅ Using device: {device}")
    gpu_available = device.type == "cuda"
    res = faiss.StandardGpuResources() if gpu_available else None

    embedding_model = SentenceTransformer(model_path).to(device)

    # --- Locate chunks.json & output dir ---
    chunk_file_path = find_chunks_json(branch_root)
    output_dir = os.path.dirname(chunk_file_path)  # save next to chunks.json

    print(f"\n📂 Chunks file: {chunk_file_path}")
    print(f"📂 Output dir:  {output_dir}")
    os.makedirs(output_dir, exist_ok=True)

    # --- Load chunks ---
    with open(chunk_file_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    metadata, texts = [], []
    for entry in chunks:
        content = clean_text(entry.get("Text", ""))
        metadata.append({
            "Id": entry.get("Id"),
            "File": entry.get("File"),
            "Class": entry.get("Class"),
            "Member": entry.get("Member"),
            "Type": entry.get("Type"),
            "Content": content
        })
        texts.append(content)

    # --- Embeddings & FAISS ---
    print(f"\n🏗️  Generating embeddings…")
    vectors = []
    batch_size = 512
    step = 1000
    for i in tqdm(range(0, len(texts), step), desc="🏗️  Batches"):
        batch = texts[i:i + step]
        batch_vectors = embedding_model.encode(batch, batch_size=batch_size, convert_to_numpy=True)
        vectors.extend(batch_vectors)
        if gpu_available:
            torch.cuda.empty_cache()

    vectors = np.array(vectors, dtype="float32")
    faiss.normalize_L2(vectors)
    dimension = vectors.shape[1]
    index = faiss.IndexFlatIP(dimension)
    if gpu_available:
        index = faiss.index_cpu_to_gpu(res, 0, index)
    index.add(vectors)

    # --- Save ---
    faiss_path = os.path.join(output_dir, "code_index.faiss")
    meta_path = os.path.join(output_dir, "metadata.json")

    faiss.write_index(faiss.index_gpu_to_cpu(index) if gpu_available else index, faiss_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Indexed {len(metadata)} chunks.")
    print(f"✅ FAISS:   {faiss_path}")
    print(f"✅ Metadata:{meta_path}\n")


if __name__ == "__main__":
    # Standalone interactive run
    build_cs_index()
