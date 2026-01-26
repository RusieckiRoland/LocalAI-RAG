# tests/retrieval/test_02_semantic_entry_point.py
from __future__ import annotations

from vector_db.semantic_searcher import load_semantic_search


QUERY = "entry point program Program.cs Startup.cs Main"
TOP_K = 12

BRANCH = "Release_FAKE_UNIVERSAL_4.60"
INDEX_ID = "fake_universal_460_490"


def test_02_semantic_entry_point_regular_code() -> None:
    searcher = load_semantic_search(index_id=INDEX_ID)

    results = searcher.search(
        QUERY,
        top_k=TOP_K,
        filters={
            "branch": BRANCH,
            "data_type": "regular_code",
        },
    )

    print("\n--- SEMANTIC SEARCH RESULTS ---")
    for r in results:
        meta = r.get("Metadata") or {}
        print(
            f"Score={r.get('FaissScore')} "
            f"Id={r.get('Id')} "
            f"File={r.get('File')} "
            f"branch={meta.get('branch')} "
            f"data_type={meta.get('data_type')}"
        )

    assert results, "Semantic search returned 0 results"

    for r in results:
        meta = r.get("Metadata") or {}
        assert meta.get("branch") == BRANCH
        assert meta.get("data_type") == "regular_code"

    # sanity: entry-point file should show up near top in fake repo
    files = [r.get("File") or "" for r in results]
    assert any("Program.cs" in f for f in files), files
