from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from vector_db.build_vector_index import load_config, resolve_path
from vector_db.tf_index import bm25_search, load_tf_index

py_logger = logging.getLogger(__name__)


def _list_subdirs(root: str) -> List[str]:
    try:
        return sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])
    except Exception:
        return []


def _passes_filters(meta: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
    """
    Metadata filter helper used by BM25 search results.

    Expected filter contract:
        filters = { "branch": ["develop"], "repository": ["RepoA"], "data_type": ["sql"] }

    Notes:
    - Comparisons are case-insensitive string equality.
    - Meta values can be scalars or lists/sets/tuples.
    """
    if not filters:
        return True

    for key, allowed_values in (filters or {}).items():
        if not allowed_values:
            continue

        # IMPORTANT: normalize string -> [string] to avoid treating a string as an iterable of chars.
        if isinstance(allowed_values, str):
            allowed_values = [allowed_values]

        # Normalize allowed values to lower-case strings.
        allowed = set(str(v).strip().lower() for v in (allowed_values or []) if str(v).strip())
        if not allowed:
            continue

        # Try a few common key casings/aliases.
        candidates = [
            meta.get(key),
            meta.get(key.lower()),
            meta.get(key.upper()),
            meta.get(key.title()),
        ]

        # Some metadata uses different field names.
        if key.lower() == "file_type":
            candidates.extend([meta.get("filetype"), meta.get("FileType")])
        if key.lower() == "data_type":
            candidates.extend([meta.get("datatype"), meta.get("kind"), meta.get("Kind")])
        if key.lower() == "branch":
            candidates.extend([meta.get("git_branch"), meta.get("branch_name"), meta.get("index_branch")])
        if key.lower() == "repository":
            candidates.extend([meta.get("repo"), meta.get("repo_name"), meta.get("index_repository")])

        val = next((v for v in candidates if v is not None), None)
        if val is None:
            return False

        if isinstance(val, (list, tuple, set)):
            values = [str(x).strip().lower() for x in val if str(x).strip()]
            if not any(v in allowed for v in values):
                return False
        else:
            s = str(val).strip().lower()
            if s not in allowed:
                return False

    return True


class Bm25Searcher:
    """
    Keyword retrieval based on TF inverted index artifacts (BM25 scoring).

    Important mapping:
        doc_id returned by bm25_search() is the FAISS row index, i.e. it maps 1:1
        to unified_metadata[doc_id] for the same unified index directory.
    """

    def __init__(self, *, index_dir: str, tf_index: Dict[str, Any], metadata: List[Dict[str, Any]]) -> None:
        self.index_dir = index_dir
        self._tf = tf_index
        self._meta = metadata

    def search(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        doc_count = int(self._tf.get("meta", {}).get("doc_count", 0) or 0)
        if doc_count <= 0:
            return []

        # Oversample to survive post-filtering (branch/repository/data_type/etc.).
        oversample = int(kwargs.get("oversample_factor") or 5)
        raw_k = max(int(top_k or 1), 1) * max(oversample, 1)
        raw_k = min(raw_k, doc_count)

        hits: List[Tuple[int, float]] = bm25_search(self._tf, q, top_k=raw_k)

        out: List[Dict[str, Any]] = []
        for doc_id, score in hits:
            if doc_id < 0 or doc_id >= len(self._meta):
                continue

            meta = self._meta[int(doc_id)] or {}
            if not _passes_filters(meta, filters):
                continue

            # Match "UnifiedSearch-ish" shape so other pipeline normalization code can digest it.
            file_path = meta.get("source_file") or meta.get("File") or meta.get("file") or ""
            text = meta.get("text") or meta.get("Text") or meta.get("Content") or meta.get("content") or ""

            out.append(
                {
                    "_score": float(score),
                    "Bm25Score": float(score),
                    "File": file_path,
                    "Id": meta.get("id") or meta.get("Id") or str(doc_id),
                    "Content": text[:400] if isinstance(text, str) and text else text,
                    "Metadata": meta,
                }
            )

            if len(out) >= int(top_k or 1):
                break

        return out


def load_bm25_search(index_id: Optional[str] = None) -> Bm25Searcher:
    """
    Load BM25 TF artifacts for the active unified index.

    Looks for files in:
        <vector_indexes_root>/<index_id>/
            tf_vocab.json
            tf_offsets.npy
            tf_doc_ids.npy
            tf_tfs.npy
            tf_df.npy
            tf_doc_len.npy
            tf_index_meta.json
            unified_metadata.json
    """
    config, config_dir = load_config()
    vector_root = resolve_path(str(config.get("vector_indexes_root", "vector_indexes")), config_dir)
    chosen_id = (index_id or str(config.get("active_index_id", "")) or "").strip()
    if not chosen_id:
        raise ValueError("active_index_id is empty; cannot load BM25 TF index")

    index_dir = os.path.join(vector_root, chosen_id)

    meta_path = os.path.join(index_dir, "unified_metadata.json")
    if not os.path.isfile(meta_path):
        available = _list_subdirs(vector_root)
        details = ""
        if available:
            details = "\nAvailable index dirs under vector_indexes_root:\n  - " + "\n  - ".join(available)
        raise FileNotFoundError(f"Missing unified_metadata.json in index_dir: {index_dir}{details}")

    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    if not isinstance(metadata, list):
        raise ValueError("unified_metadata.json must be a JSON list")

    tf_idx = load_tf_index(index_dir)

    # Best-effort sanity check.
    doc_count = int(tf_idx.get("meta", {}).get("doc_count", 0) or 0)
    if doc_count and doc_count != len(metadata):
        py_logger.warning(
            "BM25 TF index doc_count (%s) != unified_metadata rows (%s). This will cause mapping issues.",
            doc_count,
            len(metadata),
        )

    return Bm25Searcher(index_dir=index_dir, tf_index=tf_idx, metadata=metadata)
