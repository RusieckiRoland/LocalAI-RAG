from __future__ import annotations

import os
from typing import Any, Optional

from history.history_manager import HistoryManager
from integrations.plant_uml.plantuml_check import add_plant_link
import constants

from .pipeline.loader import PipelineLoader
from .pipeline.validator import PipelineValidator
from .pipeline.engine import PipelineEngine, PipelineRuntime
from .pipeline.state import PipelineState
from .pipeline.action_registry import build_default_action_registry


class DynamicPipelineRunner:
    """
    Backward-compatible wrapper used by the public endpoint and tests.

    Contract expected by tests:
    - __init__(pipelines_dir=..., main_model=..., searcher=..., markdown_translator=..., translator_pl_en=..., logger=...)
    - run(..., mock_redis=...) returns:
        (final_answer, query_type, steps_used, model_input_en)
    - module-level symbol HistoryManager must exist for monkeypatching.
    """

    def __init__(
        self,
        *,
        # Backward-compatible argument name (used in tests)
        pipelines_dir: Optional[str] = None,
        # New alias (optional)
        pipelines_root: Optional[str] = None,
        # Backward-compatible model/searcher arg names
        main_model: Any = None,
        searcher: Any = None,
        # Translators/logging
        markdown_translator: Any = None,
        translator_pl_en: Any = None,
        logger: Any = None,
        # Optional extras (kept for compatibility with newer runtime wiring)
        bm25_searcher: Any = None,
        semantic_rerank_searcher: Any = None,
        graph_provider: Any = None,
        token_counter: Any = None,
    ) -> None:
        root = pipelines_root or pipelines_dir
        if not root:
            raise TypeError("DynamicPipelineRunner requires 'pipelines_dir' or 'pipelines_root'")

        self.pipelines_dir = os.fspath(root)

        self.main_model = main_model
        self.searcher = searcher
        self.bm25_searcher = bm25_searcher
        self.semantic_rerank_searcher = semantic_rerank_searcher
        self.graph_provider = graph_provider
        self.token_counter = token_counter

        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.logger = logger

        self._loader = PipelineLoader(pipelines_root=self.pipelines_dir)
        self._validator = PipelineValidator()
        self._engine = PipelineEngine(build_default_action_registry())

    def run(
        self,
        *,
        user_query: str,
        session_id: str,
        consultant: str,
        branch: str,
        translate_chat: bool,
        mock_redis: Any,
    ):
        # Load YAML by consultant name (keeps old endpoint contract)
        pipeline_name = consultant
        pipeline = self._loader.load_by_name(pipeline_name)
        self._validator.validate(pipeline)

        # IMPORTANT: must be module-level HistoryManager (tests monkeypatch it)
        history_manager = HistoryManager(mock_redis, session_id)

        # Keep the same history behavior as current servers
        if translate_chat:
            model_input_en_for_history = self.translator_pl_en.translate(user_query)
        else:
            model_input_en_for_history = user_query

        history_manager.start_user_query(model_input_en_for_history, user_query)

        state = PipelineState(
            user_query=user_query,
            session_id=session_id,
            consultant=consultant,
            branch=branch,
            translate_chat=translate_chat,
        )

        runtime = PipelineRuntime(
            pipeline_settings=pipeline.settings,
            main_model=self.main_model,
            searcher=self.searcher,
            markdown_translator=self.markdown_translator,
            translator_pl_en=self.translator_pl_en,
            history_manager=history_manager,
            logger=self.logger,
            constants=constants,
            add_plant_link=add_plant_link,
            bm25_searcher=self.bm25_searcher,
            semantic_rerank_searcher=self.semantic_rerank_searcher,
            graph_provider=self.graph_provider,
            token_counter=self.token_counter,
        )

        self._engine.run(pipeline, state, runtime)

        final_answer = (
            state.final_answer
            or state.answer_pl
            or state.answer_en
            or "Error: No valid response generated."
        )

        return final_answer, state.query_type, state.steps_used, state.model_input_en_or_fallback()
