# tests/retrieval/test_01_bm25_entry_point.py
from __future__ import annotations

from code_query_engine.pipeline.actions.search_nodes import SearchNodesAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter
from code_query_engine.pipeline.state import PipelineState

from vector_db.bm25_searcher import load_bm25_search


class _DummyConstants:
    ANSWER_PREFIX = "[Answer:]"


def test_bm25_entry_point_program_main() -> None:
    # Payload exactly like in your test case (jsonish_v1 parser should handle it)
    payload = (
        "{\"query\":\"entry point program Program.cs Startup.cs Main\","
        "\"filters\":{\"data_type\":\"regular_code\"}}"
    )

    state = PipelineState(
        user_query="test",
        session_id="S1",
        consultant="test",
        branch="Release_FAKE_UNIVERSAL_4.60",
        translate_chat=False,
        repository="fake",
    )
    state.last_model_response = payload

    # BM25 is loaded from tests/config.json because you run pytest from tests/ (cwd)
    bm25 = load_bm25_search(index_id="fake_universal_460_490")

    dispatcher = RetrievalDispatcher(
        semantic=None,
        bm25=bm25,
        semantic_rerank=None,
    )

    backend = RetrievalBackendAdapter(
        dispatcher=dispatcher,
        graph_provider=None,
        pipeline_settings={},
    )

    runtime = PipelineRuntime(
        pipeline_settings={},
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=None,
        constants=_DummyConstants(),
        retrieval_backend=backend,
        retrieval_dispatcher=None,
        bm25_searcher=bm25,
        semantic_rerank_searcher=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=None,
    )

    step = StepDef(
        id="search",
        action="search_nodes",
        raw={
            "search_type": "bm25",
            "query_parser": "jsonish_v1",
            "top_k": 12,
        },
    )

    SearchNodesAction().do_execute(step, state, runtime)

    # Assert: BM25 must return results
    assert state.retrieval_seed_nodes, "BM25 returned no results"

    # Assert: IDs must be canonical and from correct branch
    for node_id in state.retrieval_seed_nodes:
        assert node_id.startswith(
            "fake::Release_FAKE_UNIVERSAL_4.60::"
        ), f"Non-canonical or wrong-branch id: {node_id}"

    # Assert: Program.cs entry point must be present
    assert (
        "fake::Release_FAKE_UNIVERSAL_4.60::C0001" in state.retrieval_seed_nodes
    ), state.retrieval_seed_nodes
