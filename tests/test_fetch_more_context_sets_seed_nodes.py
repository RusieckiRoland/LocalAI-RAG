from __future__ import annotations

from pathlib import Path
from typing import Any

import constants
from code_query_engine.pipeline.actions.fetch_more_context import FetchMoreContextAction
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

    def add_iteration(self, meta, faiss_results):
        return None

    def set_final_answer(self, answer_en, answer_pl):
        return None


class DummyLogger:
    def log_interaction(self, **kwargs: Any):
        return None


def _runtime(tmp_path: Path, retriever: FakeRetriever) -> PipelineRuntime:
    dispatcher = RetrievalDispatcher(semantic=retriever, bm25=retriever, semantic_rerank=retriever)

    return PipelineRuntime(
        pipeline_settings={"top_k": 3, "test": True},
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
        add_plant_link=lambda x, *_: x,
    )


def test_fetch_more_context_sets_retrieval_seed_nodes_from_ids(tmp_path: Path) -> None:
    action = FetchMoreContextAction()

    retriever = FakeRetriever(
        results=[
            {"Id": "A", "File": "a.py", "Content": "AAA"},
            {"Id": "B", "File": "b.py", "Content": "BBB"},
            {"Id": "A", "File": "a.py", "Content": "AAA-dup"},
        ]
    )

    runtime = _runtime(tmp_path, retriever)

    step = StepDef(id="fetch", action="fetch_more_context", raw={"id": "fetch", "action": "fetch_more_context"})

    state = PipelineState(
        user_query="x",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )
    state.retrieval_mode = "semantic"
    state.retrieval_query = "what"
    state.context_blocks = []

    action.execute(step, state, runtime)

    assert state.retrieval_seed_nodes == ["A", "B"]
