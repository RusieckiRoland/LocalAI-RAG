# tests/retrieval/test_08_bm25_prefilter_file_type.py
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

import pytest

# Ensure project root is importable when running pytest from ./tests
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from vector_db.bm25_searcher import Bm25Searcher
from vector_db.tf_index import build_tf_index, load_tf_index


def _build_searcher(tmp_path: Any, *, texts: List[str], metadata: List[Dict[str, Any]]) -> Bm25Searcher:
    index_dir = tmp_path / "tf_index"
    index_dir.mkdir(parents=True, exist_ok=True)

    # Build TF artifacts on disk, then load exactly as production code does.
    build_tf_index(texts, str(index_dir))
    tf = load_tf_index(str(index_dir))

    return Bm25Searcher(index_dir=str(index_dir), tf_index=tf, metadata=metadata)


def test_08_bm25_prefilter_happens_before_scoring_not_post_filtering(tmp_path: Any) -> None:
    """
    HARD PROOF test.

    If filtering is applied only AFTER global top_k truncation (BUG):
      - global top_k is all SQL
      - filtering file_type=cs returns EMPTY

    If filtering is applied BEFORE scoring (CORRECT):
      - BM25 scores only CS docs
      - results are NON-EMPTY
    """
    # Many SQL docs: contain both query terms -> dominate global top_k.
    sql_text = ("foo " * 6 + "bar " * 6).strip()

    # CS docs: contain only one term -> weaker globally, but should be returned when filtered.
    cs_text = ("foo " * 1).strip()

    texts: List[str] = []
    metadata: List[Dict[str, Any]] = []

    for i in range(30):
        texts.append(sql_text)
        metadata.append({"id": f"sql_{i}", "file_type": "sql", "source_file": f"Db{i}.sql"})

    for i in range(3):
        texts.append(cs_text)
        metadata.append({"id": f"cs_{i}", "file_type": "cs", "source_file": f"Code{i}.cs"})

    searcher = _build_searcher(tmp_path, texts=texts, metadata=metadata)

    query = "foo bar"

    # Sanity: global top_k should be SQL-only for this constructed corpus.
    global_hits = searcher.search(query, top_k=5, filters=None)
    assert global_hits, "Global BM25 returned empty results (unexpected for constructed corpus)"
    assert all((r.get("Metadata") or {}).get("file_type") == "sql" for r in global_hits), (
        "Global top_k is expected to be SQL-only for this corpus.\n"
        f"Got: {[ (r.get('Id'), (r.get('Metadata') or {}).get('file_type')) for r in global_hits ]}"
    )

    # HARD ASSERT:
    # With file_type=cs we MUST still get CS hits.
    cs_hits = searcher.search(query, top_k=2, filters={"file_type": "cs"})
    assert cs_hits, (
        "Expected non-empty results for file_type=cs.\n"
        "If this is empty, you are post-filtering after truncation (BUG)."
    )
    assert all((r.get("Metadata") or {}).get("file_type") == "cs" for r in cs_hits), (
        f"Filtered hits must be CS-only. Got: {[ (r.get('Id'), (r.get('Metadata') or {}).get('file_type')) for r in cs_hits ]}"
    )


def test_08_bm25_filters_match_nothing_returns_empty_list(tmp_path: Any) -> None:
    texts = ["foo bar", "foo bar", "foo"]
    metadata = [
        {"id": "sql_0", "file_type": "sql", "source_file": "Db0.sql"},
        {"id": "sql_1", "file_type": "sql", "source_file": "Db1.sql"},
        {"id": "cs_0", "file_type": "cs", "source_file": "Code0.cs"},
    ]

    searcher = _build_searcher(tmp_path, texts=texts, metadata=metadata)

    out = searcher.search("foo bar", top_k=5, filters={"file_type": "__nope__"})
    assert out == []
