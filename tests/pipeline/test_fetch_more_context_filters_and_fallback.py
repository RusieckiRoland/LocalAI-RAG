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


def test_search_nodes_merges_branch_and_repo_filters():
    step = StepDef(
        id="fetch",
        action="search_nodes",
        raw={
            "id": "fetch",
            "action": "search_nodes",
            # NEW contract: search_type is defined on the step (YAML), not in state.
            "search_type": "bm25",
        },
    )

    retr = FakeRetriever(results=[{"Id": "X", "path": "a.cs", "content": "x"}])

    # NOTE: semantic_rerank removed from dispatcher API (rerank is internal, not a mode).
    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr)

    rt = _runtime({"branch": "develop", "repository": "nopCommerce", "top_k": 2}, dispatcher)

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rej",
        branch="develop",
        translate_chat=False,
    )
    state.retrieval_mode = "bm25"
    state.retrieval_filters = {"data_type": "regular_code"}

    # NEW contract: query comes from router payload (prefix stripped).
    state.last_model_response = "Main entry point"

    # NOTE: state.search_type is no longer required as input.
    SearchNodesAction().execute(step, state, rt)

    # Ensure filters were merged into retriever call
    assert retr.calls, "Expected retriever.search to be called"
    call = retr.calls[-1]
    assert call["filters"].get("branch") == "develop"
    assert call["filters"].get("repo") == "nopCommerce"
    assert call["filters"].get("data_type") == "regular_code"


def test_search_nodes_returns_gracefully_when_missing_dispatcher():
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

    rt = PipelineRuntime(
        pipeline_settings={"top_k": 2},
        model=FakeModelClient(outputs=[""]),
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistory(),
        logger=DummyLogger(),
        constants=constants,
        retrieval_dispatcher=None,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rej",
        branch="develop",
        translate_chat=False,
    )
    state.retrieval_mode = "semantic"

    # NEW contract: query comes from router payload (prefix stripped).
    state.last_model_response = "something"

    # Should not throw
    SearchNodesAction().execute(step, state, rt)
