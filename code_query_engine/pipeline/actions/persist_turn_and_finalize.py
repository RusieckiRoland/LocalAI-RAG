# code_query_engine/pipeline/actions/persist_turn_and_finalize.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from typing import Any, Dict
from .base_action import PipelineActionBase



class PersistTurnAndFinalizeAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "persist_turn_and_finalize"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {
            "user_query": state.user_query,
            "model_input_en": state.model_input_en_or_fallback(),
            "answer_en": getattr(state, "answer_en", None),
            "answer_pl": getattr(state, "answer_pl", None),
            "last_model_response": getattr(state, "last_model_response", None),
            "draft_answer_en": getattr(state, "draft_answer_en", None),
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
        # Persist step is terminal usually, but keep next for completeness.
        return {
            "next_step_id": next_step_id,
            "final_answer": getattr(state, "final_answer", None),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # In the assessment pipeline, the last model response may be the assessor routing line.
        last_model_response = state.draft_answer_en or state.last_model_response or ""

        answer_out = state.answer_en or last_model_response
        try:
            if bool(getattr(state, "translate_chat", False)) and getattr(state, "answer_pl", None):
                answer_out = state.answer_pl or answer_out
        except Exception:
            pass

        logger = getattr(runtime, "logger", None)
        log_fn = getattr(logger, "log_interaction", None)

        if callable(log_fn):
            # Prefer the "ports" logger signature if available, fall back to legacy kwargs.
            data = {
                "user_question": state.user_query,
                "translate_chat": bool(getattr(state, "translate_chat", False)),
                "translated_question_en": state.model_input_en_or_fallback(),
                "consultant": getattr(state, "consultant", "") or "",
                "branch_a": getattr(state, "branch", "") or "",
                "branch_b": getattr(state, "branch_b", None),
                "answer": answer_out,
            }

            try:
                log_fn(
                    session_id=state.session_id,
                    pipeline_name=getattr(state, "pipeline_name", "") or "",
                    step_id=step.id,
                    action=step.action,
                    data=data,
                )
            except TypeError:
                # Legacy fallback (older runtime/tests). New InteractionLogger can pick up missing
                # fields from metadata even in this mode.
                try:
                    log_fn(
                        original_question=state.user_query,
                        model_input_en=state.model_input_en_or_fallback(),
                        codellama_response=last_model_response,
                        final_answer=answer_out,
                        metadata={
                            "consultant": data["consultant"],
                            "branch_a": data["branch_a"],
                            "branch_b": data["branch_b"],
                            "translate_chat": data["translate_chat"],
                        },
                    )
                except TypeError:
                    pass

        # Persist final answer in history (best-effort)
        try:
            runtime.history_manager.set_final_answer(state.answer_en or "", state.answer_pl)
        except Exception:
            pass

        return None
