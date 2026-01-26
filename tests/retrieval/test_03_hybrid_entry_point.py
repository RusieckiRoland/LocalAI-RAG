from __future__ import annotations

from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchRequest

from vector_db.bm25_searcher import load_bm25_search
from vector_db.semantic_searcher import load_semantic_search


INDEX_ID = "fake_universal_460_490"
REPO = "fake"
BRANCH = "Release_FAKE_UNIVERSAL_4.60"

QUERY = "entry point program Program.cs Startup.cs Main"
TOP_K = 12


def test_03_hybrid_entry_point_regular_code_scope_plus_filters() -> None:
    """
    HYBRID retrieval contract test.

    Scope:
      - repository: fake
      - branch: Release_FAKE_UNIVERSAL_4.60

    Filters (ACL):
      - data_type: regular_code

    Expected:
      - returns at least 1 hit
      - IDs must be canonical and limited to requested BRANCH
      - rank is 1-based
    """

    semantic = load_semantic_search(index_id=INDEX_ID)
    bm25 = load_bm25_search(index_id=INDEX_ID)

    dispatcher = RetrievalDispatcher(semantic=semantic, bm25=bm25)

    backend = RetrievalBackendAdapter(
        dispatcher=dispatcher,
        graph_provider=None,
        pipeline_settings={
            "hybrid_widen": 1,   # deterministic for tests
            "hybrid_rrf_k": 60,  # stable
        },
    )

    req = SearchRequest(
        search_type="hybrid",
        query=QUERY,
        top_k=TOP_K,
        repository=REPO,   # ✅ scope
        branch=BRANCH,     # ✅ scope
        retrieval_filters={
            "data_type": "regular_code",  # ✅ only real ACL filters
        },
        active_index=INDEX_ID,
    )

    resp = backend.search(req)

    print("\n--- HYBRID SEARCH HITS ---")
    for h in resp.hits:
        print(f"rank={h.rank} score={h.score:.6f} id={h.id}")

    assert resp.hits, "Hybrid search returned 0 results"

    # Contract: 1-based rank
    assert resp.hits[0].rank == 1, "Rank must be 1-based"

    # Contract: NO branch leakage
    assert all(f"::{BRANCH}::" in h.id for h in resp.hits), "Hybrid leaked results from other branches"
