# search_engine.py
import os
import json
import faiss
import torch
from sentence_transformers import SentenceTransformer
from transformers import MarianMTModel, MarianTokenizer

# ===============================
# 🔹 Configuration and paths
# ===============================
script_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.join(script_dir, "..")
config_path = os.path.join(base_dir, "config.json")

with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

branch = config.get("branch", "").strip()  # may be empty

# Paths to FAISS index and metadata
rag_bundles = os.path.join(base_dir, config["output_dir"])
regular_code_bundle = (
    os.path.join(rag_bundles, branch, "regular_code_bundle")
    if branch else os.path.join(rag_bundles, "regular_code_bundle")
)

faiss_index_path = os.path.join(regular_code_bundle, "code_index.faiss")
metadata_path = os.path.join(regular_code_bundle, "metadata.json")
chunks_code_path = os.path.join(regular_code_bundle, "chunks.json")
dependencies_path = os.path.join(regular_code_bundle, "dependencies.json")

# Model paths
model_path = os.path.join(base_dir, config["model_path_embd"])
# IMPORTANT: make sure in config.json this is "models/translation/pl_en/Helsinki_NLPopus_mt_pl_en"
pl_en_model_dir = os.path.join(base_dir, config["model_translation_pl_en"])

# Debug — show active paths
print(f"📂 FAISS index:      {faiss_index_path}")
print(f"📂 Metadata:         {metadata_path}")
print(f"📂 Chunks:           {chunks_code_path}")
print(f"📂 Dependencies:     {dependencies_path}")
print(f"📂 Model:            {model_path}")

# ===============================
# 🔹 Device and models
# ===============================
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
embed_model = SentenceTransformer(model_path, device=device)
translator_tokenizer = MarianTokenizer.from_pretrained(pl_en_model_dir)
translator_model = MarianMTModel.from_pretrained(pl_en_model_dir).to(device)

# ===============================
# 🔹 Load data
# ===============================
index = faiss.read_index(faiss_index_path)

with open(metadata_path, "r", encoding="utf-8") as f:
    metadata = json.load(f)

with open(chunks_code_path, "r", encoding="utf-8") as f:
    chunks = json.load(f)

with open(dependencies_path, "r", encoding="utf-8") as f:
    dependencies = json.load(f)

# Map: id -> chunk
id_to_chunk = {c["Id"]: c for c in chunks}

# ===============================
# 🔹 Search functions
# ===============================
def query_faiss(query: str, branch: str, top_k: int = 5):
    """Searches for code chunks matching the query, including dependencies."""
    embedding = embed_model.encode([f"query: {query}"], convert_to_numpy=True)
    distances, indices = index.search(embedding, top_k * 5)

    results = []
    visited = set()

    for i, idx in enumerate(indices[0]):
        if idx == -1 or idx in visited:
            continue
        visited.add(idx)

        result = metadata[idx]
        chunk_id = result.get("Id")
        if chunk_id is None:
            continue

        chunk = id_to_chunk.get(chunk_id)
        if not chunk:
            continue

        related_ids = dependencies.get(str(chunk_id), [])
        related_chunks = [
            {
                "File": id_to_chunk[rel_id]["File"],
                "Member": id_to_chunk[rel_id].get("Member", "Unknown"),
                "Type": id_to_chunk[rel_id].get("Type", "Unknown"),
                "Content": id_to_chunk[rel_id]["Text"]
            }
            for rel_id in related_ids
            if rel_id in id_to_chunk and rel_id not in visited
        ]
        related_chunks.sort(key=lambda x: x["File"])

        results.append({
            "Rank": len(results) + 1,
            "File": chunk["File"],
            "Id": chunk_id,
            "Content": chunk["Text"],
            "Distance": float(distances[0][i]),
            "Related": related_chunks
        })

        if len(results) >= top_k:
            break

    return results


def format_results_as_text(results):
    """Formats search results as readable text output."""
    lines = []

    for res in results:
        lines.append(
            f"🔹 Rank {res['Rank']} | File: {res['File']} | ID: {res['Id']} "
            f"(Distance: {res['Distance']:.4f})"
        )
        lines.append(res["Content"])
        lines.append("")

        if res.get("Related"):
            lines.append("  🔗 Dependencies:")
            for rel in res["Related"]:
                lines.append(f"    ➤ {rel['File']} | {rel['Member']} ({rel['Type']})")
                lines.append(f"       {rel['Content']}\n")
        else:
            lines.append("  No dependencies for this chunk.")

    return "\n".join(lines) if lines else "❌ No results found!"
