from __future__ import annotations

import constants

from code_query_engine.pipeline.actions.search_nodes import SearchNodesAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.fakes import FakeModelClient, FakeRetriever
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.state import PipelineState


class DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class DummyMarkdownTranslator:
    def translate(self, markdown_en: str) -> str:
        return markdown_en


class DummyHistory:
    def get_context_blocks(self):
        return []

    def add_iteration(self, followup, faiss_results):
        return None

    def set_final_answer(self, answer_en, answer_pl):
        return None


class DummyLogger:
    def log_interaction(self, **kwargs):
        return None


def _runtime(pipe_settings, dispatcher):
    return PipelineRuntime(
        pipeline_settings=pipe_settings,
        model=FakeModelClient(outputs=[""]),
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistory(),
        logger=DummyLogger(),
        constants=constants,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

def test_search_nodes_accepts_File_Content_keys_and_line_range():
    step = StepDef(
        id="fetch",
        action="search_nodes",
        raw={
            "id": "fetch",
            "action": "search_nodes",
            # NEW contract: search_type is defined on the step (YAML), not in state.
            "search_type": "semantic",
        },
    )

    retr = FakeRetriever(
        results=[
            {
                "Id": "NODE1",
                "File": "src/a.cs",
                "Content": "HELLO",
                "start_line": 10,
                "end_line": 20,
            }
        ]
    )
    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr)
    rt = _runtime({"top_k": 1}, dispatcher)

    state = PipelineState(
        user_query="Q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )
    state.retrieval_mode = "semantic"

    # NEW contract: query comes from router output (prefix stripped).
    state.last_model_response = "query"

    # NOTE: state.search_type is no longer used as input.
    SearchNodesAction().execute(step, state, rt)

    # NEW contract: search_nodes outputs ONLY IDs (no context materialization).
    assert state.context_blocks == []
    assert state.retrieval_seed_nodes == ["NODE1"]
