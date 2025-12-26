# NOTE: This module exposes build_sql_index(branch_root=None, branch_zip=None)
# - If branch_root is provided: uses it directly (no ZIP selection, no extraction).
# - Else if branch_zip is provided: extracts it and uses the resulting folder.
# - Else: runs in interactive mode (lists ZIPs and asks the user).
#
# Logging file: vector_build_sql.log

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
import csv
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from collections import defaultdict

from vector_db.build_vector_index import extract_to_named_root


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


def find_sql_bodies_jsonl(branch_root: str):
    """
    Find sql_bodies.jsonl (prefer: */sql_bundle/docs/sql_bodies.jsonl).
    Also supports sql_code_bundle (legacy name).

    Returns: (jsonl_path, output_dir, edges_csv_path or None)
    """
    preferred = os.path.join(branch_root, "sql_bundle", "docs", "sql_bodies.jsonl")
    if os.path.isfile(preferred):
        edges_csv = os.path.join(branch_root, "sql_bundle", "graph", "edges.csv")
        out_dir = os.path.dirname(preferred)
        return preferred, out_dir, edges_csv if os.path.isfile(edges_csv) else None

    preferred_legacy = os.path.join(branch_root, "sql_code_bundle", "docs", "sql_bodies.jsonl")
    if os.path.isfile(preferred_legacy):
        edges_csv = os.path.join(branch_root, "sql_code_bundle", "graph", "edges.csv")
        out_dir = os.path.dirname(preferred_legacy)
        return preferred_legacy, out_dir, edges_csv if os.path.isfile(edges_csv) else None

    alt = os.path.join(branch_root, "docs", "sql_bodies.jsonl")
    if os.path.isfile(alt):
        edges_csv = os.path.join(branch_root, "graph", "edges.csv")
        out_dir = os.path.dirname(alt)
        return alt, out_dir, edges_csv if os.path.isfile(edges_csv) else None

    for root, _dirs, files in os.walk(branch_root):
        if "sql_bodies.jsonl" in files:
            jsonl_path = os.path.join(root, "sql_bodies.jsonl")
            # try to detect sibling graph/edges.csv
            maybe_graph = os.path.normpath(os.path.join(root, "..", "graph", "edges.csv"))
            edges_csv = maybe_graph if os.path.isfile(maybe_graph) else None
            return jsonl_path, root, edges_csv

    raise FileNotFoundError("sql_bodies.jsonl not found under " + branch_root)


def load_edges(edges_csv_path):
    """
    Read edges.csv and build:
      - edges_out[key][relation] = set(to_key, ...)
      - ef_refs_to[key] = set(from_csharp_key, ...)  (C#→SQL references)
    """
    edges_out = defaultdict(lambda: defaultdict(set))
    ef_refs_to = defaultdict(set)

    if not edges_csv_path or not os.path.isfile(edges_csv_path):
        return edges_out, ef_refs_to

    with open(edges_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            frm = (row.get("from") or row.get("From") or "").strip()
            to = (row.get("to") or row.get("To") or "").strip()
            relation = (row.get("relation") or row.get("Relation") or "").strip()
            if not frm or not to:
                continue

            edges_out[frm][relation].add(to)

            # Keep inbound references from C# to this SQL object
            if frm.lower().startswith("csharp:"):
                ef_refs_to[to].add(frm)

    return edges_out, ef_refs_to


def format_relations_block(key, edges_out, ef_refs_to):
    """Render a short header with relations around the 'key' object."""
    lines = []
    rel_order = ["ReadsFrom", "WritesTo", "Calls", "Executes", "FK", "On", "SynonymFor"]

    if key in edges_out:
        for rel in rel_order:
            tos = sorted(edges_out[key].get(rel, []), key=lambda s: s.lower())
            if tos:
                short = [t.split("|")[0] for t in tos]
                lines.append(f"{rel}: " + ", ".join(short))

    ef_srcs = sorted(ef_refs_to.get(key, []), key=lambda s: s.lower())
    if ef_srcs:
        def pretty_csharp(k):
            try:
                core = k.split("csharp:", 1)[1]
                left, kind = core.split("|", 1)
                return f"{left} ({kind})"
            except Exception:
                return k
        lines.append("ReferencedBy(C#): " + ", ".join(pretty_csharp(x) for x in ef_srcs))

    return "\n".join(lines)


def split_into_chunks(text, max_chars=4000):
    """Simple char-based chunker that tries not to cut lines awkwardly."""
    if len(text) <= max_chars:
        return [(text, 1, 1)]
    chunks = []
    i = 0
    while i < len(text):
        j = min(i + max_chars, len(text))
        if j < len(text):
            k = text.rfind("\n", i, j)
            if k != -1 and k > i + 1000:
                j = k
        chunks.append(text[i:j])
        i = j
    N = len(chunks)
    return [(c, idx + 1, N) for idx, c in enumerate(chunks)]


# ===============================
# 🔹 Public API
# ===============================
def build_sql_index(branch_root: str | None = None, branch_zip: str | None = None):
    """
    Build FAISS index for SQL objects (optionally enriched with relation headers).

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

    logging.basicConfig(filename="vector_build_sql.log", level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    os.makedirs(branches_dir, exist_ok=True)

    # --- Determine branch_root (priority: explicit branch_root → branch_zip → interactive) ---
    if branch_root and os.path.isdir(branch_root):
        print(f"\n📂 Using provided branch_root: {branch_root}")
    else:
        if branch_zip and os.path.isfile(branch_zip):
            print(f"\n🧩 Extracting provided archive: {os.path.basename(branch_zip)} → {branches_dir}")
            branch_root = extract_to_named_root(branch_zip, branches_dir)
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
                branch_root = extract_to_named_root(chosen_zip, branches_dir)
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

    # --- Locate sql_bodies.jsonl (+ optional edges.csv) ---
    sql_bodies_path, output_dir, edges_csv_path = find_sql_bodies_jsonl(branch_root)
    print(f"\n📂 sql_bodies.jsonl: {sql_bodies_path}")
    print(f"📂 Output dir:       {output_dir}")
    if edges_csv_path:
        print(f"📂 edges.csv:        {edges_csv_path}")
    else:
        print("ℹ️ edges.csv not found — building embeddings without relation headers.")

    # --- Load edges (optional) ---
    edges_out, ef_refs_to = load_edges(edges_csv_path)

    # --- Read jsonl & build records ---
    print("\n📖 Reading sql_bodies.jsonl and assembling records…")

    def make_header(kind, schema, name, file_path, key):
        header = [f"[{kind}] {schema}.{name}", f"file: {file_path}"]
        rel_block = format_relations_block(key, edges_out, ef_refs_to)
        if rel_block:
            header.append(rel_block)
        header.append("---")
        return "\n".join(header)

    metadata = []
    texts = []
    total = 0

    with open(sql_bodies_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            key = obj.get("key") or obj.get("Key")
            kind = obj.get("kind") or obj.get("Kind")
            schema = obj.get("schema") or obj.get("Schema")
            name = obj.get("name") or obj.get("Name")
            file_path = obj.get("file") or obj.get("File")
            body = obj.get("body") or obj.get("Body") or ""
            body = clean_text(body)

            header = make_header(kind, schema, name, file_path, key)
            full_text = f"{header}\n{body}"

            for chunk_text, part, parts in split_into_chunks(full_text, max_chars=4000):
                meta = {
                    "Key": key,
                    "Kind": kind,
                    "Schema": schema,
                    "Name": name,
                    "File": file_path,
                    "Part": part,
                    "Parts": parts
                }
                metadata.append(meta)
                texts.append(chunk_text)
                total += 1

    print(f"✅ Prepared {total} records for embedding (after chunking).")

    # --- Embeddings & FAISS ---
    print(f"\n🏗️  Generating embeddings…")
    vectors = []
    batch_size = 512
    step = 1000
    for i in tqdm(range(0, len(texts), step), desc="🏗️  Batches"):
        batch = texts[i:i + step]
        batch_vectors = embedding_model.encode(batch, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
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
    faiss_path = os.path.join(output_dir, "sql_index.faiss")
    meta_path = os.path.join(output_dir, "sql_metadata.json")

    faiss.write_index(faiss.index_gpu_to_cpu(index) if gpu_available else index, faiss_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Indexed {len(metadata)} SQL records.")
    print(f"✅ FAISS:    {faiss_path}")
    print(f"✅ Metadata: {meta_path}\n")


if __name__ == "__main__":
    # Standalone interactive run
    build_sql_index()
