# File: tests/test_search_nodes_sets_seed_nodes.py
from __future__ import annotations

from typing import Any, Dict, Optional

import constants

from code_query_engine.pipeline.actions.search_nodes import SearchNodesAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.fakes import FakeRetriever
from code_query_engine.pipeline.providers.retrieval import RetrievalDecision, RetrievalDispatcher
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter
from code_query_engine.pipeline.state import PipelineState


class DummyInteractionLogger:
    def log_interaction(self, *args: Any, **kwargs: Any) -> None:
        return


class DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class DummyMarkdownTranslator:
    def translate_markdown(self, text: str) -> str:
        return text


class DummyHistoryManager:
    def start_user_query(self, *args: Any, **kwargs: Any) -> None:
        return

    def set_final_answer(self, *args: Any, **kwargs: Any) -> None:
        return

    def get_dialog(self, *args: Any, **kwargs: Any) -> list[dict[str, str]]:
        return []


def _runtime(pipeline_settings: Dict[str, Any], dispatcher: RetrievalDispatcher) -> PipelineRuntime:
    backend = RetrievalBackendAdapter(dispatcher=dispatcher, graph_provider=None, pipeline_settings=pipeline_settings)
    return PipelineRuntime(
        pipeline_settings=pipeline_settings,
        model=None,  # not used by search_nodes
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistoryManager(),
        logger=DummyInteractionLogger(),
        constants=constants,
        retrieval_backend=backend,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda text, consultant=None: text,
    )


def test_search_nodes_sets_retrieval_seed_nodes_from_ids():
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
                "Id": "A",
                "path": "a.cs",
                "content": "class A {}",
            }
        ]
    )

    # semantic_rerank was removed from dispatcher API (rerank is internal, not a mode)
    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr)
    rt = _runtime({"top_k": 2, "repository": "nopCommerce"}, dispatcher)

    state = PipelineState(
        user_query="Q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    state.retrieval_mode = "semantic"
    state.retrieval_filters = {}

    # NEW contract: query comes from router output (prefix stripped payload)
    state.last_model_response = "query"

    # Execute
    SearchNodesAction().execute(step, state, rt)

    # Seed nodes come from IDs returned by retriever
    assert state.retrieval_seed_nodes == ["A"]
