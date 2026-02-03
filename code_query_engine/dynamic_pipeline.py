from __future__ import annotations

import logging
import os
from typing import Any, Optional

from code_query_engine.pipeline.providers.ports import IRetrievalBackend
import constants
from history.history_manager import HistoryManager
from integrations.plant_uml.plantuml_check import add_plant_link

from .pipeline.action_registry import build_default_action_registry
from .pipeline.engine import PipelineEngine, PipelineRuntime
from .pipeline.loader import PipelineLoader
from .pipeline.providers.retrieval import RetrievalDispatcher
from .pipeline.state import PipelineState
from .pipeline.validator import PipelineValidator

py_logger = logging.getLogger(__name__)



def _create_history_manager(*, mock_redis: Any, session_id: str, consultant: str, user_id: Optional[str]):
    """
    HistoryManager signature changed a few times; keep this tolerant for tests/mocks.
    """
    candidates = [
        lambda: HistoryManager(mock_redis=mock_redis, session_id=session_id, consultant=consultant, user_id=user_id),
        lambda: HistoryManager(mock_redis=mock_redis, session_id=session_id, consultant=consultant),
        lambda: HistoryManager(mock_redis, session_id=session_id, consultant=consultant, user_id=user_id),
        lambda: HistoryManager(mock_redis, session_id=session_id, user_id=user_id),
        lambda: HistoryManager(mock_redis, session_id=session_id),
        lambda: HistoryManager(mock_redis, session_id, user_id),
        lambda: HistoryManager(mock_redis, session_id),
    ]

    last_err: Optional[Exception] = None
    for ctor in candidates:
        try:
            return ctor()
        except TypeError as e:
            last_err = e

    # If we got here, no signature matched.
    raise last_err or TypeError("Unable to construct HistoryManager with provided arguments.")


class DynamicPipelineRunner:
    def __init__(
        self,
        *,
        pipelines_dir: Optional[str] = None,
        pipelines_root: Optional[str] = None,
        model: Any = None,
        retrieval_backend: IRetrievalBackend | None = None,
        markdown_translator: Any = None,
        translator_pl_en: Any = None,
        logger: Any = None,        
        semantic_rerank_searcher: Any = None,
        graph_provider: Any = None,
        token_counter: Any = None,
        allow_test_pipelines: bool = False,
    ) -> None:
        root = pipelines_root or pipelines_dir
        if not root:
            raise TypeError("DynamicPipelineRunner requires pipelines_root/pipelines_dir")

        self.pipelines_root = os.fspath(root)
        self.model = model       
        self.retrieval_backend = retrieval_backend       
        self.semantic_rerank_searcher = semantic_rerank_searcher

        if graph_provider is None:
            # No fallback: graph provider must be injected explicitly.
            graph_provider = None

        self.graph_provider = graph_provider
        self.token_counter = token_counter

        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.logger = logger

        self.allow_test_pipelines = bool(allow_test_pipelines)

        self._loader = PipelineLoader(pipelines_root=self.pipelines_root)
        self._validator = PipelineValidator()

        # Engine needs an action registry (tests may override runner._engine anyway).
        self._engine = PipelineEngine(registry=build_default_action_registry())

    def run(
        self,
        *,
        user_query: str,
        session_id: str,
        consultant: str,
        branch: str = "",
        translate_chat: bool = False,
        user_id: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        repository: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        snapshot_set_id: Optional[str] = None,
        overrides: Optional[dict[str, Any]] = None,
        mock_redis: Any = None,
    ):
        pipe_name = pipeline_name or consultant

        # ✅ Correct loader API
        pipeline = self._loader.load_by_name(pipe_name)
        self._validator.validate(pipeline)

        # ✅ Block test pipelines unless explicitly allowed (required by E2E test)
        if bool((pipeline.settings or {}).get("test")) and not self.allow_test_pipelines:
            raise PermissionError("Test pipelines are blocked unless allow_test_pipelines=True")

        effective_settings = dict(pipeline.settings or {})
        if overrides:
            effective_settings.update(dict(overrides))

        state = PipelineState(
            user_query=user_query,
            session_id=session_id,
            consultant=consultant,
            branch=branch,
            translate_chat=bool(translate_chat),
            user_id=user_id,
            repository=repository,
            snapshot_id=snapshot_id,
            snapshot_set_id=snapshot_set_id,
        )

        if repository:
            state.repository = repository

        if overrides:
            # Common ad-hoc request fields used by UI (best-effort).
            if "branch_b" in overrides:
                setattr(state, "branch_b", overrides.get("branch_b"))
            if "snapshot_id" in overrides and not snapshot_id:
                setattr(state, "snapshot_id", overrides.get("snapshot_id"))
            if "snapshot_set_id" in overrides and not snapshot_set_id:
                setattr(state, "snapshot_set_id", overrides.get("snapshot_set_id"))
            # Optional retrieval filters (e.g., ACL tags) resolved by the server.
            retrieval_filters = overrides.get("retrieval_filters")
            if isinstance(retrieval_filters, dict):
                state.retrieval_filters.update(retrieval_filters)

        history_manager = _create_history_manager(
            mock_redis=mock_redis,
            session_id=session_id,
            consultant=consultant,
            user_id=user_id,
        )

        

        retrieval_backend = self.retrieval_backend
        if retrieval_backend is None:
            raise ValueError("DynamicPipelineRunner: retrieval_backend is required.")

        # ✅ Match PipelineRuntime signature (no action_registry kwarg here)
        runtime = PipelineRuntime(
            pipeline_settings=effective_settings,
            model=self.model,
            searcher=None,
            markdown_translator=self.markdown_translator,
            translator_pl_en=self.translator_pl_en,
            history_manager=history_manager,
            logger=self.logger,
            constants=constants,
            retrieval_backend=retrieval_backend,
            graph_provider=self.graph_provider,
            token_counter=self.token_counter,
            add_plant_link=add_plant_link,
        )

        self._engine.run(pipeline, state, runtime)

        final_answer = state.final_answer or state.answer_en or ""
        query_type = state.query_type or state.retrieval_mode or None
        steps_used = state.steps_used
        model_input_en = state.model_input_en_or_fallback()

        return final_answer, query_type, steps_used, model_input_en
