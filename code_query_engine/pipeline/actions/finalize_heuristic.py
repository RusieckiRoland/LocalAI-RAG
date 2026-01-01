# code_query_engine/pipeline/actions/finalize_heuristic.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from typing import Any, Dict
from .base_action import PipelineActionBase


class FinalizeHeuristicAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "finalize_heuristic"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {
            "draft_answer_en": getattr(state, "draft_answer_en", None),
            "last_model_response": getattr(state, "last_model_response", None),
            "answer_en_before": getattr(state, "answer_en", None),
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
            "answer_en_after": getattr(state, "answer_en", None),
            "query_type": getattr(state, "query_type", None),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        if state.answer_en:
            return None

        # Assessment pipeline fallback: if we have a draft answer, accept it.
        if state.draft_answer_en and state.draft_answer_en.strip():
            state.answer_en = state.draft_answer_en.strip()
            state.query_type = "draft accepted (heuristic)"
            return None

        resp = (state.last_model_response or "").strip()

        if resp.startswith(runtime.constants.ANSWER_PREFIX):
            state.answer_en = resp.replace(runtime.constants.ANSWER_PREFIX, "").strip()
            state.query_type = "direct answer"
            return None

        # In test pipelines we accept any non-empty model output as an answer.
        # This keeps E2E tests deterministic even for short replies like "OK".
        settings = runtime.pipeline_settings or {}
        if bool(settings.get("test")) and resp:
            state.answer_en = resp
            state.query_type = "direct answer (test)"
            return None

        # Heuristic: accept a non-trivial response as final answer
        if len(resp) > 20:
            state.answer_en = resp
            state.query_type = "direct answer (heuristic)"
        else:
            state.answer_en = "Unrecognized response from model."
            state.query_type = "fallback error"

        return None

