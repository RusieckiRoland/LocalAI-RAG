# tests/retrieval/test_04_semantic_keyword_rerank_entry_point.py
from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

# Ensure project root is importable when running from ./tests
_THIS_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
sys.path.insert(0, _PROJECT_ROOT)

from vector_db.semantic_searcher import load_semantic_search
from vector_db.bm25_searcher import load_bm25_search

from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter
from code_query_engine.pipeline.providers.file_system_graph_provider import FileSystemGraphProvider
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchRequest


REPO = "fake"
BRANCH = "Release_FAKE_UNIVERSAL_4.60"
INDEX_ID = "fake_universal_460_490"

QUERY = "entry point program Program.cs Startup.cs Main"

TOP_K = 12
WIDEN_FACTOR = 6
CANDIDATE_K = TOP_K * WIDEN_FACTOR


def _keyword_overlap_score(query: str, text: str) -> int:
    """
    Very simple keyword score: counts how many query tokens appear in text.
    Enough for contract testing (we only need a deterministic signal).
    """
    if not text:
        return 0

    q = query.lower()
    t = text.lower()

    tokens = []
    for raw in q.replace(".", " ").replace(":", " ").replace(",", " ").split():
        v = raw.strip()
        if len(v) >= 2:
            tokens.append(v)

    hits = 0
    for tok in tokens:
        if tok in t:
            hits += 1
    return hits


def test_04_semantic_keyword_rerank_entry_point_regular_code_scope_enforced() -> None:
    """
    Contract test: semantic retrieval + keyword_rerank.

    Scope:
      - repository = REPO  (like connection string DB name)
      - branch     = BRANCH (MUST be enforced, because it's a different folder)

    Filters (ACL):
      - data_type = regular_code

    Expected today:
      ✅ semantic search returns some hits
      ✅ ALL hits MUST belong to BRANCH (scope enforced!)
      ✅ fetch_texts returns non-empty texts for at least some candidates
      ✅ keyword rerank can reorder candidates and return TOP_K results
    """

    semantic = load_semantic_search(index_id=INDEX_ID)
    bm25 = load_bm25_search(index_id=INDEX_ID)

    dispatcher = RetrievalDispatcher(semantic=semantic, bm25=bm25)

    # IMPORTANT: we are in ./tests, and fake repos are in ./tests/repositories
    graph_provider = FileSystemGraphProvider(repositories_root="repositories")

    backend = RetrievalBackendAdapter(
        dispatcher=dispatcher,
        graph_provider=graph_provider,
        pipeline_settings={
            "active_index": INDEX_ID,
        },
    )

    # ---------------------------
    # 1) Semantic widened search
    # ---------------------------
    # NOTE: repo+branch are SCOPE (not filters)
    # Only real ACL filters go into retrieval_filters.
    sem_req = SearchRequest(
        search_type="semantic",
        query=QUERY,
        top_k=CANDIDATE_K,
        repository=REPO,
        branch=BRANCH,
        retrieval_filters={
            "data_type": "regular_code",
        },
        active_index=INDEX_ID,
    )

    sem_resp = backend.search(sem_req)
    assert sem_resp.hits, "Semantic search returned 0 hits."

    ids = [h.id for h in sem_resp.hits]

    # ---------------------------
    # 2) Scope MUST be enforced
    # ---------------------------
    # If this fails -> backend leaks across branches
    # (exactly what we observed in your hybrid output).
    bad = [x for x in ids if f"{REPO}::{BRANCH}::" not in x]
    if bad:
        print("\n--- SCOPE VIOLATION: hits leaked outside requested BRANCH ---")
        for x in bad[:20]:
            print("LEAKED:", x)
        raise AssertionError(
            f"Scope violation: search returned {len(bad)} hits outside branch '{BRANCH}'. "
            f"This means RetrievalBackendAdapter.search() does NOT enforce scope."
        )

    # ---------------------------
    # 3) Fetch texts for rerank
    # ---------------------------
    texts_by_id = backend.fetch_texts(
        node_ids=ids,
        repository=REPO,
        branch=BRANCH,
        active_index=INDEX_ID,
        retrieval_filters={
            "data_type": "regular_code",
        },
    )

    non_empty = [nid for nid in ids if (texts_by_id.get(nid) or "").strip()]
    if not non_empty:
        print("\n--- FETCH_TEXTS DIAGNOSTIC ---")
        print("Candidate IDs (first 12):")
        for nid in ids[:12]:
            print(" ", nid)
        print("\nMapping returned keys (first 12):")
        for k in list(texts_by_id.keys())[:12]:
            v = texts_by_id.get(k) or ""
            print(" ", k, "len(text)=", len(v))
        raise AssertionError(
            "All fetched texts are empty -> keyword_rerank cannot work. "
            "Either fetch_texts is broken, OR scope is leaking and IDs don't match branch folder."
        )

    # ---------------------------
    # 4) Keyword rerank (local)
    # ---------------------------
    scored: List[Tuple[str, int]] = []
    for nid in ids:
        scored.append((nid, _keyword_overlap_score(QUERY, texts_by_id.get(nid) or "")))

    scored.sort(key=lambda x: (-x[1], x[0]))  # deterministic

    reranked_ids = [nid for (nid, score) in scored if score > 0][:TOP_K]

    print("\n--- KEYWORD RERANK TOP ---")
    for i, nid in enumerate(reranked_ids, start=1):
        print(f"rank={i} id={nid} score={dict(scored).get(nid)}")

    assert reranked_ids, "Keyword rerank produced 0 results (no token overlap)."
    assert len(reranked_ids) <= TOP_K
