# code_query_engine/pipeline/engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .action_registry import ActionRegistry
from .definitions import PipelineDef, StepDef
from .providers.ports import (
    IGraphProvider,
    IHistoryManager,
    IInteractionLogger,
    IMarkdownTranslatorEnPl,
    IModelClient,
    IRetriever,
    ITokenCounter,
    ITranslatorPlEn,
)
from .providers.retrieval import RetrievalDispatcher


@dataclass
class PipelineResult:
    # Execution
    steps_used: int
    step_trace: List[str]

    # Answers (expected by tests)
    answer_en: Optional[str]
    answer_pl: Optional[str]

    # Final view
    final_answer: str
    query_type: str
    followup_query: Optional[str]
    model_input_en: str


class PipelineRuntime:
    """
    Runtime DI container expected by existing actions and tests.
    """

    def __init__(
        self,
        *,
        pipeline_settings: Dict[str, Any],
        main_model: IModelClient,
        searcher: Optional[IRetriever],
        markdown_translator: Optional[IMarkdownTranslatorEnPl],
        translator_pl_en: Optional[ITranslatorPlEn],
        history_manager: IHistoryManager,
        logger: IInteractionLogger,
        constants: Any,
        retrieval_dispatcher: Optional[RetrievalDispatcher] = None,
        bm25_searcher: Optional[IRetriever] = None,
        semantic_rerank_searcher: Optional[IRetriever] = None,
        graph_provider: Optional[IGraphProvider] = None,
        token_counter: Optional[ITokenCounter] = None,
        add_plant_link: Optional[Any] = None,
    ) -> None:
        self.pipeline_settings = pipeline_settings or {}
        self.main_model = main_model
        self.searcher = searcher
        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.history_manager = history_manager
        self.logger = logger
        self.constants = constants

        self.retrieval_dispatcher = retrieval_dispatcher
        self.bm25_searcher = bm25_searcher
        self.semantic_rerank_searcher = semantic_rerank_searcher

        self.graph_provider = graph_provider
        self.token_counter = token_counter
        self.add_plant_link = add_plant_link or (lambda x: x)

        # Useful debug
        self.last_model_output: Optional[str] = None

    def get_retrieval_dispatcher(self) -> RetrievalDispatcher:
        if self.retrieval_dispatcher is not None:
            return self.retrieval_dispatcher

        # Fallback dispatcher built from individual searchers (may still be None => dispatcher returns [])
        return RetrievalDispatcher(
            semantic=self.searcher,
            bm25=self.bm25_searcher,
            semantic_rerank=self.semantic_rerank_searcher,
        )


class PipelineEngine:
    """
    Executes steps sequentially. Action decides branching by returning next step id.
    If action returns None, engine follows step.next. If step.end==True => stop.
    """

    def __init__(self, actions: Optional[ActionRegistry] = None, *, registry: Optional[ActionRegistry] = None) -> None:
        # Backward-compat: tests use PipelineEngine(registry=...)
        self._actions = registry or actions
        if self._actions is None:
            raise ValueError("PipelineEngine requires an ActionRegistry instance.")

    def run(self, pipeline: PipelineDef, state: Any, runtime: PipelineRuntime) -> PipelineResult:
        settings = pipeline.settings or {}
        current_step_id = (settings.get("entry_step_id") or "").strip()
        if not current_step_id:
            raise ValueError("Pipeline settings must define 'entry_step_id'.")

        steps_by_id = pipeline.steps_by_id()

        state.pipeline_name = pipeline.name
        state.steps_used = 0
        state.step_trace = []

        while current_step_id:
            step: StepDef = steps_by_id.get(current_step_id)  # type: ignore[assignment]
            if step is None:
                raise KeyError(f"Unknown step id: '{current_step_id}'")

            state.steps_used += 1
            state.step_trace.append(current_step_id)

            action = self._actions.get(step.action)

            # Actions in repo are mixed: some use positional, some keyword-only.
            next_step_id: Optional[str]
            try:
                next_step_id = action.execute(step, state, runtime)  # type: ignore[attr-defined]
            except TypeError:
                next_step_id = action.execute(step=step, state=state, runtime=runtime)  # type: ignore[attr-defined]

            # stop if this step is terminal
            if bool(step.end):
                break

            # action override
            if next_step_id:
                current_step_id = next_step_id
                continue

            # default next from YAML
            if step.next:
                current_step_id = step.next
                continue

            break

        # Resolve final answer (what the caller sees)
        final_answer = state.answer_en or ""
        if getattr(state, "translate_chat", False) and state.answer_pl:
            final_answer = state.answer_pl

        state.final_answer = final_answer

        return PipelineResult(
            steps_used=state.steps_used,
            step_trace=list(state.step_trace),
            answer_en=state.answer_en,
            answer_pl=state.answer_pl,
            final_answer=final_answer,
            query_type=state.query_type or "",
            followup_query=state.followup_query,
            model_input_en=state.model_input_en_or_fallback(),
        )
