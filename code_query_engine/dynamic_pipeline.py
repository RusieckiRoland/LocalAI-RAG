# code_query_engine/dynamic_pipeline.py
from __future__ import annotations

import os
from typing import Any, Optional

import constants
from history.history_manager import HistoryManager
from integrations.plant_uml.plantuml_check import add_plant_link

from .pipeline.action_registry import build_default_action_registry
from .pipeline.engine import PipelineEngine, PipelineRuntime
from .pipeline.loader import PipelineLoader
from .pipeline.state import PipelineState
from .pipeline.validator import PipelineValidator


class DynamicPipelineRunner:
    def __init__(
        self,
        *,
        pipelines_dir: Optional[str] = None,
        pipelines_root: Optional[str] = None,
        main_model: Any = None,
        searcher: Any = None,
        markdown_translator: Any = None,
        translator_pl_en: Any = None,
        logger: Any = None,
        bm25_searcher: Any = None,
        semantic_rerank_searcher: Any = None,
        graph_provider: Any = None,
        token_counter: Any = None,
        allow_test_pipelines: bool = False,
    ) -> None:
        root = pipelines_root or pipelines_dir
        if not root:
            raise TypeError("DynamicPipelineRunner requires pipelines_root/pipelines_dir")

        self.pipelines_root = os.fspath(root)

        self.main_model = main_model
        self.searcher = searcher
        self.bm25_searcher = bm25_searcher
        self.semantic_rerank_searcher = semantic_rerank_searcher
        if graph_provider is None:
            try:
                from .pipeline.providers.graph_provider import GraphProvider

                graph_provider = GraphProvider()
            except Exception:
                graph_provider = None

        self.graph_provider = graph_provider

        self.token_counter = token_counter

        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.logger = logger

        self.allow_test_pipelines = bool(allow_test_pipelines)

        self._loader = PipelineLoader(pipelines_root=self.pipelines_root)
        self._validator = PipelineValidator()
        self._engine = PipelineEngine(build_default_action_registry())

    def _create_history_manager(self, mock_redis: Any, session_id: str) -> Any:
        # Try production signatures first, then test/dummy signatures.
        constructors = [
            lambda: HistoryManager(backend=mock_redis, session_id=session_id),
            lambda: HistoryManager(mock_redis, session_id=session_id),
            lambda: HistoryManager(mock_redis),
            lambda: HistoryManager(session_id=session_id),
            lambda: HistoryManager(),
        ]
        last_exc: Optional[Exception] = None
        for ctor in constructors:
            try:
                return ctor()
            except Exception as exc:
                last_exc = exc
                continue
        # Re-raise last error to aid debugging
        if last_exc:
            raise last_exc
        raise TypeError("Could not construct HistoryManager")

    def run(
        self,
        *,
        user_query: str,
        session_id: str,
        consultant: str,
        branch: str,
        translate_chat: bool = False,
        user_id: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        repository: Optional[str] = None,
        mock_redis: Any = None,
    ):
        pipe_name = (pipeline_name or consultant or "").strip()
        if not pipe_name:
            pipe_name = "default"

        pipeline = self._loader.load_by_name(pipe_name)
        self._validator.validate(pipeline)

        if bool(pipeline.settings.get("test")) and not self.allow_test_pipelines:
            raise PermissionError("Test pipelines are blocked unless allow_test_pipelines=True")

        state = PipelineState(
            user_query=user_query,
            session_id=session_id,
            user_id=user_id,
            consultant=consultant,
            branch=branch,
            translate_chat=translate_chat,
        )
        if repository:
            state.repository = repository

        history_manager = self._create_history_manager(mock_redis, session_id)

        runtime = PipelineRuntime(
            pipeline_settings=pipeline.settings,
            main_model=self.main_model,
            searcher=self.searcher,
            markdown_translator=self.markdown_translator,
            translator_pl_en=self.translator_pl_en,
            history_manager=history_manager,
            logger=self.logger,
            constants=constants,
            retrieval_dispatcher=None,
            bm25_searcher=self.bm25_searcher,
            semantic_rerank_searcher=self.semantic_rerank_searcher,
            graph_provider=self.graph_provider,
            token_counter=self.token_counter,
            add_plant_link=add_plant_link,
        )

        self._engine.run(pipeline, state, runtime)

        final_answer = state.final_answer or state.answer_en or ""
        query_type = state.query_type or state.retrieval_mode
        if not query_type:
            query_type = None
        steps_used = state.steps_used
        model_input_en = state.model_input_en_or_fallback()

        return final_answer, query_type, steps_used, model_input_en
