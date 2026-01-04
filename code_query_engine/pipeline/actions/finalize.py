# code_query_engine/pipeline/actions/finalize.py
from __future__ import annotations

import logging
from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from typing import Any, Dict
from .base_action import PipelineActionBase

py_logger = logging.getLogger(__name__)


class FinalizeAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "finalize"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {
            "translate_chat": bool(getattr(state, "translate_chat", False)),
            "consultant": getattr(state, "consultant", None),
            "answer_en": getattr(state, "answer_en", None),
        }

    def log_out(
        self,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
        *,
        next_step_id: Optional[str],
        error: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "next_step_id": next_step_id,
            "final_answer": getattr(state, "final_answer", None),
            "answer_pl": getattr(state, "answer_pl", None),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        answer = state.answer_en or "Error: No valid response generated."

        # Translate only when requested and not for UML consultant
        if state.translate_chat and (state.consultant != runtime.constants.UML_CONSULTANT):
            try:
                state.answer_pl = runtime.markdown_translator.translate_markdown(answer)
                state.final_answer = state.answer_pl
            except Exception:
                py_logger.exception("soft-failure: markdown translation failed; using English answer")
                state.final_answer = answer
        else:
            state.final_answer = answer

        # PlantUML link
        try:
            state.final_answer = runtime.add_plant_link(state.final_answer, state.consultant)
        except Exception:
            py_logger.exception("soft-failure: add_plant_link failed; continuing without PlantUML link")
            pass

        return None
