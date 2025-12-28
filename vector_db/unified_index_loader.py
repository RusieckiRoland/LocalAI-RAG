"""
Unified index loader for LocalAI-RAG.

Responsibilities:
- Load config.json using the existing helper from build_vector_index.py
- Resolve the active unified index directory:
    vector_indexes_root / active_index_id
- Load:
    - FAISS index (unified_index.faiss)
    - metadata list (unified_metadata.json)
    - embedding model (same as used for building)
- Construct and return a UnifiedSearch instance.

This module does NOT:
- run FAISS build,
- modify metadata,
- know anything about the dynamic pipeline.
"""

from __future__ import annotations

import json
import os
from typing import Tuple, List, Dict, Any

import faiss
from sentence_transformers import SentenceTransformer

from vector_db.build_vector_index import load_config, resolve_path
from vector_search.unified_search import UnifiedSearch
from vector_search.models import VectorSearchRequest, VectorSearchFilters  # noqa: F401


def _load_config_and_paths() -> Tuple[dict, str]:
    """
    Load config.json using the same mechanism as build_vector_index.py.

    Returns:
        config:     dictionary loaded from config.json
        config_dir: directory holding config.json (used as base for relative paths)
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # We reuse the existing helper; it knows how to find config.json
    config, config_dir = load_config(script_dir)
    return config, config_dir


def _list_subdirs(root: str) -> List[str]:
    """
    Return sorted list of immediate subdirectory names under root.
    """
    try:
        if not os.path.isdir(root):
            return []
        out: List[str] = []
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if os.path.isdir(full):
                out.append(name)
        out.sort(key=lambda x: x.lower())
        return out
    except Exception:
        return []


def _resolve_index_paths(config: dict, config_dir: str, index_id: str | None = None) -> Tuple[str, str, str]:
    """
    Resolve paths for the unified index artifacts.

    Directory structure:
        <vector_indexes_root>/<index_id>/

    Config keys:
        vector_indexes_root  (default: "vector_indexes")
        active_index_id      (default: "nop_main_index")
    """
    root = resolve_path(config.get("vector_indexes_root", "vector_indexes"), config_dir)
    chosen_id = index_id or config.get("active_index_id", "nop_main_index")
    index_dir = os.path.join(root, chosen_id)
    return root, chosen_id, index_dir


def _load_faiss_and_metadata(
    *,
    index_dir: str,
    vector_root: str,
    index_id: str,
) -> Tuple[faiss.Index, List[Dict[str, Any]]]:
    """
    Load FAISS index and metadata JSON from a given directory.

    Expected files:
        unified_index.faiss
        unified_metadata.json
    """
    faiss_path = os.path.join(index_dir, "unified_index.faiss")
    meta_path = os.path.join(index_dir, "unified_metadata.json")

    if not os.path.isfile(faiss_path):
        available = _list_subdirs(vector_root)
        details = ""
        if available:
            details = (
                "\nAvailable index dirs under vector_indexes_root:\n  - "
                + "\n  - ".join(available)
            )
        raise FileNotFoundError(
            "FAISS index not found: "
            f"{faiss_path}\n"
            f"Requested index_id: {index_id}\n"
            f"vector_indexes_root: {vector_root}"
            f"{details}"
        )

    if not os.path.isfile(meta_path):
        available = _list_subdirs(vector_root)
        details = ""
        if available:
            details = (
                "\nAvailable index dirs under vector_indexes_root:\n  - "
                + "\n  - ".join(available)
            )
        raise FileNotFoundError(
            "Metadata file not found: "
            f"{meta_path}\n"
            f"Requested index_id: {index_id}\n"
            f"vector_indexes_root: {vector_root}"
            f"{details}"
        )

    index = faiss.read_index(faiss_path)

    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    if not isinstance(metadata, list):
        raise ValueError(f"Metadata JSON must be a list, got {type(metadata)}")

    # Critical invariant: FAISS row_id must align 1:1 with metadata rows.
    if hasattr(index, "ntotal") and index.ntotal != len(metadata):
        raise ValueError(
            f"FAISS index size ({getattr(index, 'ntotal', 'n/a')}) "
            f"does not match metadata length ({len(metadata)})"
        )

    return index, metadata


def _load_embedding_model(config: dict, config_dir: str):
    """
    Load the embedding model used for unified index search.

    Uses:
        config["model_path_embd"]
    """
    model_path = config.get("model_path_embd")
    if not model_path:
        raise KeyError("model_path_embd is not defined in config.json")

    abs_model_path = resolve_path(model_path, config_dir)
    if not os.path.exists(abs_model_path):
        # We allow both local paths and HF model ids; existence check is best-effort.
        print(f"[UnifiedIndexLoader] Warning: model path does not exist on disk: {abs_model_path}")

    model = SentenceTransformer(abs_model_path)
    return model


def load_unified_search(index_id: str | None = None) -> UnifiedSearch:
    """
    Load the active unified index and return a UnifiedSearch instance.

    Args:
        index_id: override index id; if None, uses config["active_index_id"].

    Returns:
        UnifiedSearch configured with:
        - FAISS index from unified_index.faiss
        - metadata from unified_metadata.json
        - embedding model from model_path_embd
    """
    config, config_dir = _load_config_and_paths()
    vector_root, chosen_id, index_dir = _resolve_index_paths(config, config_dir, index_id=index_id)

    index, metadata = _load_faiss_and_metadata(index_dir=index_dir, vector_root=vector_root, index_id=chosen_id)
    embed_model = _load_embedding_model(config, config_dir)

    # Construct UnifiedSearch – this is the main entry point for vector queries.
    searcher = UnifiedSearch(index=index, metadata=metadata, embed_model=embed_model)
    return searcher
