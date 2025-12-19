from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import constants
from .definitions import PipelineDef, StepDef
from .state import PipelineState
from .action_registry import ActionRegistry
from .providers.ports import (
    IHistoryManager,
    IInteractionLogger,
    IMarkdownTranslatorEnPl,
    IModelClient,
    ITranslatorPlEn,
)
from .providers.retrieval import RetrievalDispatcher


@dataclass
class PipelineRuntime:
    pipeline_settings: Dict[str, Any]
    main_model: IModelClient
    searcher: Optional[Any]  # deprecated, keep for backward compat
    markdown_translator: IMarkdownTranslatorEnPl
    translator_pl_en: ITranslatorPlEn
    history_manager: IHistoryManager
    logger: IInteractionLogger
    constants: Any = constants
    retrieval_dispatcher: Optional[RetrievalDispatcher] = None
    bm25_searcher: Optional[Any] = None
    semantic_rerank_searcher: Optional[Any] = None
    graph_provider: Optional[Any] = None
    token_counter: Optional[Any] = None
    add_plant_link: Optional[Any] = None

    def get_retrieval_dispatcher(self) -> RetrievalDispatcher:
        if self.retrieval_dispatcher is None:
            # Backward compatible construction
            self.retrieval_dispatcher = RetrievalDispatcher(
                semantic=getattr(self, "searcher", None),
                semantic_rerank=getattr(self, "semantic_rerank_searcher", None),
                bm25=getattr(self, "bm25_searcher", None),
            )
        return self.retrieval_dispatcher


class PipelineEngine:    
    def __init__(self, action_registry=None, registry=None) -> None:
        # Backward compatibility: tests/older code use "registry="
        self._actions = action_registry or registry
        if self._actions is None:
            raise TypeError("PipelineEngine requires 'action_registry' (or legacy 'registry')")


    def run(self, pipeline: PipelineDef, state: PipelineState, runtime: PipelineRuntime) -> PipelineState:
        step_id = pipeline.settings.get("entry_step_id") or pipeline.entry_step_id
        visited = 0

        while True:
            visited += 1
            state.steps_used = visited

            steps_by_id = pipeline.steps_by_id()
            step = steps_by_id.get(step_id)
            if step is None:
                raise RuntimeError(f"Engine reached missing step id: '{step_id}'")
            action = self._actions.get(step.action)

            nxt = action.execute(step, state, runtime)

            # Step.next may be used as default next transition
            step_id = nxt or step.next

            if step.end:
                break

        return state
