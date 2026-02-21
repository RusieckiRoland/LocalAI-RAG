from __future__ import annotations

import logging
import uuid
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
            "answer_neutral": getattr(state, "answer_neutral", None),
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
        # - Otherwise -> final_answer = answer_neutral.
        #
        # NOTE: This action does NOT populate answer_neutral/answer_translated. Upstream steps must do it.
        answer_neutral = (state.answer_neutral or "").strip()
        answer_translated = (state.answer_translated or "").strip()
        banner_neutral = (getattr(state, "banner_neutral", None) or "").strip()
        banner_translated = (getattr(state, "banner_translated", None) or "").strip()

        if bool(getattr(state, "translate_chat", False)):
            if banner_translated:
                state.final_answer = f"{banner_translated}\n\n{answer_translated}"
            else:
                state.final_answer = answer_translated
        else:
            if banner_neutral:
                state.final_answer = f"{banner_neutral}\n\n{answer_neutral}"
            else:
                state.final_answer = answer_neutral

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

        persist_answer_neutral = (state.answer_neutral or "").strip()
        persist_answer_translated = (state.answer_translated or "").strip() or None
        if bool(getattr(state, "translate_chat", False)):
            persist_answer_translated = answer_out
        else:
            persist_answer_neutral = answer_out

        # Write question/answer in neutral + translated form (single current path).
        svc = getattr(runtime, "conversation_history_service", None)
        on_started = getattr(svc, "on_request_started", None) if svc is not None else None
        on_finalized = getattr(svc, "on_request_finalized", None) if svc is not None else None
        if callable(on_started) and callable(on_finalized):
            try:
                request_id = str(getattr(state, "request_id", "") or "").strip() or str(uuid.uuid4())
                setattr(state, "request_id", request_id)

                question_neutral = state.model_input_en_or_fallback()
                question_translated = None
                if bool(getattr(state, "translate_chat", False)):
                    question_translated = (getattr(state, "user_question_translated", None) or state.user_query) or None

                turn_id = on_started(
                    session_id=state.session_id,
                    request_id=request_id,
                    identity_id=getattr(state, "user_id", None),
                    translate_chat=bool(getattr(state, "translate_chat", False)),
                    question_neutral=question_neutral,
                    question_translated=question_translated,
                    meta={
                        "pipeline_name": getattr(state, "pipeline_name", "") or "",
                        "consultant": getattr(state, "consultant", "") or "",
                        "repository": getattr(state, "repository", None),
                        "snapshot_id": getattr(state, "snapshot_id", None),
                    },
                )
                setattr(state, "conversation_turn_id", turn_id)

                answer_neutral = persist_answer_neutral
                answer_translated = persist_answer_translated
                translated_is_fallback = None
                if bool(getattr(state, "translate_chat", False)):
                    if answer_translated:
                        translated_is_fallback = False
                    else:
                        answer_translated = answer_neutral
                        translated_is_fallback = True

                on_finalized(
                    session_id=state.session_id,
                    request_id=request_id,
                    identity_id=getattr(state, "user_id", None),
                    turn_id=turn_id,
                    answer_neutral=answer_neutral,
                    answer_translated=answer_translated,
                    answer_translated_is_fallback=translated_is_fallback,
                    meta=None,
                )
            except Exception:
                py_logger.exception("soft-failure: conversation_history_service write failed; continuing")

        return None
