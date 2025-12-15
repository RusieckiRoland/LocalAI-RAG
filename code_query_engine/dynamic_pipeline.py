# code_query_engine/dynamic_pipeline.py
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
    Thin wrapper:
      load -> validate -> engine.run(state)
    """

    def __init__(
        self,
        *,
        pipelines_dir: str,
        main_model: Any,
        searcher: Any,
        markdown_translator: Any,
        translator_pl_en: Any,
        logger: Any,
    ) -> None:
        self.pipelines_dir = pipelines_dir
        self.main_model = main_model
        self.searcher = searcher
        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.logger = logger

        self._loader = PipelineLoader(pipelines_root=pipelines_dir)
        self._validator = PipelineValidator()
        self._engine = PipelineEngine(registry=build_default_action_registry())

    def run(
        self,
        user_query: str,
        session_id: str,
        consultant: str,
        branch: str,
        *,
        translate_chat: bool,
        mock_redis: Any,
    ):
        # Load YAML by consultant name (keeps old endpoint contract)
        pipeline_name = consultant
        pipeline = self._loader.load_by_name(pipeline_name)
        self._validator.validate(pipeline)

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
        )

        self._engine.run(pipeline, state, runtime)

        final_answer = state.final_answer or state.answer_pl or state.answer_en or "Error: No valid response generated."
        return final_answer, state.query_type, state.steps_used, state.model_input_en_or_fallback()
