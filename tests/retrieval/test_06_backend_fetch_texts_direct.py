# tests/retrieval/test_06_backend_fetch_texts_direct.py
from __future__ import annotations

import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from code_query_engine.pipeline.providers.file_system_graph_provider import FileSystemGraphProvider
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter


REPO = "fake"
BRANCH = "Release_FAKE_UNIVERSAL_4.60"
INDEX_ID = "fake_universal_460_490"

NODE_IDS = [
    "fake::Release_FAKE_UNIVERSAL_4.60::C0001",
    "fake::Release_FAKE_UNIVERSAL_4.60::C0002",
    "fake::Release_FAKE_UNIVERSAL_4.60::C0178",
]


def test_06_backend_fetch_texts_direct() -> None:
    graph_provider = FileSystemGraphProvider(repositories_root="repositories")
    dispatcher = RetrievalDispatcher(semantic=None, bm25=None, semantic_rerank=None)

    backend = RetrievalBackendAdapter(
        dispatcher=dispatcher,
        graph_provider=graph_provider,
        pipeline_settings={"active_index": INDEX_ID},
    )

    texts_by_id = backend.fetch_texts(
        node_ids=NODE_IDS,
        repository=REPO,
        branch=BRANCH,
        active_index=INDEX_ID,
        retrieval_filters={
            "branch": BRANCH,
            "data_type": "regular_code",
        },
    )

    print("\n--- BACKEND.FETCH_TEXTS DIRECT ---")
    for nid in NODE_IDS:
        txt = (texts_by_id.get(nid) or "")
        print(f"id={nid} text_len={len(txt)}")

    assert texts_by_id, "backend.fetch_texts returned empty mapping"
    assert any((texts_by_id.get(n) or "").strip() for n in NODE_IDS), "ALL fetched texts are empty"
