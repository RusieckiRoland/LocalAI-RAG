# code_query_engine/pipeline/actions/translate_in_if_needed.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from typing import Any, Dict
from .base_action import PipelineActionBase


class TranslateInIfNeededAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "translate_in_if_needed"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        tr = getattr(runtime, "translator_pl_en", None)
        return {
            "translate_chat": bool(getattr(state, "translate_chat", False)),
            "translator_present": bool(tr is not None and hasattr(tr, "translate")),
            "user_query": state.user_query,
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
            "user_question_en": state.user_question_en,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        tr = runtime.translator_pl_en
        model_language = str((getattr(runtime, "pipeline_settings", {}) or {}).get("model_language") or "").strip().lower()
        if model_language == "neutral":
            # Neutral language: never translate. Use the original user query directly.
            state.translate_chat = False
            state.user_question_en = state.user_query
            return None

        if state.translate_chat and tr is not None and hasattr(tr, "translate"):
            state.user_question_en = tr.translate(state.user_query)
        else:
            state.user_question_en = state.user_query

        return None
