from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase

py_logger = logging.getLogger(__name__)


class FinalizeAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "finalize"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {
            "consultant": getattr(state, "consultant", None),
            "answer_en": getattr(state, "answer_en", None),
            "answer_translated": getattr(state, "answer_translated", None),
            "last_model_response": getattr(state, "last_model_response", None),
            "persist_turn": bool((step.raw or {}).get("persist_turn", True)),
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
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        persist_enabled = bool(raw.get("persist_turn", True))

        # Finalize materializes the user-visible answer:
        # - If translate_chat is enabled and answer_translated is present -> final_answer = answer_translated.
        # - Otherwise -> final_answer = answer_en.
        #
        # NOTE: This action does NOT populate answer_en/answer_translated. Upstream steps must do it.
        answer_en = (state.answer_en or "").strip()
        answer_translated = (state.answer_translated or "").strip()

        if bool(getattr(state, "translate_chat", False)) and answer_translated:
            state.final_answer = answer_translated
        else:
            state.final_answer = answer_en

        if not persist_enabled:
            return None

        # Persist/log the finalized result (best-effort).
        answer_out = str(state.final_answer or "")

        logger = getattr(runtime, "logger", None)
        log_fn = getattr(logger, "log_interaction", None)

        if callable(log_fn):
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
                # Legacy fallback (older runtime/tests).
                try:
                    log_fn(
                        original_question=state.user_query,
                        model_input_en=state.model_input_en_or_fallback(),
                        codellama_response=(state.last_model_response or "").strip(),
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

        try:
            runtime.history_manager.set_final_answer(state.answer_en or "", state.answer_translated)
        except Exception:
            py_logger.exception("soft-failure: history_manager.set_final_answer failed; continuing")
            pass

        return None
