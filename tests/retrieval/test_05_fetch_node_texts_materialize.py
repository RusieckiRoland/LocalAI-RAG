# tests/retrieval/test_05_fetch_node_texts_materialize.py
from __future__ import annotations

import os
import sys

# Ensure project root is importable when running pytest from ./tests
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import constants  # ✅ REQUIRED by PipelineRuntime

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.file_system_graph_provider import FileSystemGraphProvider
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter
from code_query_engine.pipeline.state import PipelineState


REPO = "fake"
BRANCH = "Release_FAKE_UNIVERSAL_4.60"
INDEX_ID = "fake_universal_460_490"

SEED_NODE_IDS = [
    "fake::Release_FAKE_UNIVERSAL_4.60::C0001",
    "fake::Release_FAKE_UNIVERSAL_4.60::C0002",
    "fake::Release_FAKE_UNIVERSAL_4.60::C0178",
    "fake::Release_FAKE_UNIVERSAL_4.60::C0105",
    "fake::Release_FAKE_UNIVERSAL_4.60::C0128",
]


class SimpleTokenCounter:
    """
    Minimal deterministic token counter for tests.
    fetch_node_texts requires count_tokens(...) or count(...).
    """

    def count_tokens(self, text: str) -> int:
        return len((text or "").split())

    def count(self, text: str) -> int:
        return self.count_tokens(text)


def test_05_fetch_node_texts_materializes_non_empty_texts_for_regular_code() -> None:
    """
    Contract test: fetch_node_texts action must materialize texts for provided node IDs.

    Filters (ACL):
      - branch   (mandatory)
      - data_type = regular_code

    Expected:
      - state.node_texts has entries for requested node IDs
      - at least ONE entry has non-empty text
      - if texts are empty -> this reproduces the same "empty fetch_texts" bug
    """

    # IMPORTANT:
    # We run from ./tests and fake repos are in ./tests/repositories
    graph_provider = FileSystemGraphProvider(repositories_root="repositories")

    # Dispatcher not used by fetch_node_texts, but backend requires it.
    dispatcher = RetrievalDispatcher(semantic=None, bm25=None, semantic_rerank=None)

    backend = RetrievalBackendAdapter(
        dispatcher=dispatcher,
        graph_provider=graph_provider,
        pipeline_settings={
            "active_index": INDEX_ID,
        },
    )

    runtime = PipelineRuntime(
        pipeline_settings={
            "active_index": INDEX_ID,
            "max_context_tokens": 8000,
        },
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=None,
        constants=constants,  # ✅ FIX: required argument
        retrieval_backend=backend,
        retrieval_dispatcher=None,  # contract: retrieval actions must use backend only
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=graph_provider,
        token_counter=SimpleTokenCounter(),
        add_plant_link=lambda x, consultant=None: x,
    )

    state = PipelineState(
        user_query="TEST fetch_node_texts",
        session_id="TEST_SESSION",
        consultant="TEST",
        branch=BRANCH,
        translate_chat=False,
        repository=REPO,
    )

    # What we want to materialize
    state.retrieval_seed_nodes = list(SEED_NODE_IDS)

    # MANDATORY FILTERS:
    # - branch must be present
    # - data_type is ACL
    state.retrieval_filters = {
        "branch": BRANCH,
        "data_type": "regular_code",
    }

    step = StepDef(
        id="fetch_node_texts",
        action="fetch_node_texts",
        raw={
            "budget_tokens": 50000,            
            "prioritization_mode": "seed_first",
            # optional: "next": None  # not needed for unit test
        },
    )


    action = FetchNodeTextsAction()
    action.execute(step, state, runtime)

    node_texts = list(getattr(state, "node_texts", []) or [])

    print("\n--- FETCH_NODE_TEXTS RESULT ---")
    print(f"requested_ids={len(SEED_NODE_IDS)} materialized={len(node_texts)}")
    for i, item in enumerate(node_texts[:12]):
        _id = item.get("id")
        txt = (item.get("text") or "")
        print(f"{i:02d} id={_id} text_len={len(txt)}")

    assert node_texts, "fetch_node_texts produced 0 node_texts items (unexpected)."

    non_empty = [x for x in node_texts if (x.get("text") or "").strip()]
    assert non_empty, (
        "fetch_node_texts returned ONLY EMPTY texts.\n"
        "This reproduces the bug in materialization:\n"
        "- RetrievalBackendAdapter.fetch_texts(...) returns empty strings\n"
        "- OR FileSystemGraphProvider cannot resolve bundle files for this branch\n"
        "- OR canonical->local ID mapping is wrong\n"
    )
