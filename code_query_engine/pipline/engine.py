# code_query_engine/pipeline/engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Dict

from .definitions import PipelineDef
from .state import PipelineState
from .action_registry import ActionRegistry


@dataclass(frozen=True)
class PipelineRuntime:
    # Pipeline-level settings (needed by budget checks etc.)
    pipeline_settings: Dict[str, Any]

    # Core deps
    main_model: Any
    searcher: Any
    markdown_translator: Any
    translator_pl_en: Any
    history_manager: Any
    logger: Any

    # Misc helpers
    constants: Any
    add_plant_link: Any

    # Optional providers (future)
    bm25_searcher: Any = None
    graph_provider: Any = None
    token_counter: Any = None


class PipelineEngine:
    """Deterministic State Machine runner: step -> action -> transition."""

    def __init__(self, registry: ActionRegistry) -> None:
        self._registry = registry

    def run(self, pipeline: PipelineDef, state: PipelineState, runtime: PipelineRuntime) -> PipelineState:
        steps_by_id = pipeline.steps_by_id()
        current_step_id = (pipeline.settings.get("entry_step_id") or "").strip()

        # Hard safety limit against bad configs
        max_steps = max(len(pipeline.steps) + 25, 50)

        for i in range(max_steps):
            if not current_step_id:
                break
            step = steps_by_id.get(current_step_id)
            if step is None:
                raise RuntimeError(f"Engine reached missing step id: '{current_step_id}'")

            state.steps_used = i + 1

            action_obj = self._registry.get(step.action)
            next_step_id = getattr(action_obj, "execute")(step, state, runtime)  # type: ignore[attr-defined]

            if step.end:
                break

            if next_step_id is None:
                next_step_id = step.raw.get("next")

            current_step_id = next_step_id

        return state
