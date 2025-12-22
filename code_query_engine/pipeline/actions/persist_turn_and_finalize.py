# code_query_engine/pipeline/actions/persist_turn_and_finalize.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class PersistTurnAndFinalizeAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # In the assessment pipeline, the last model response may be the assessor routing line.
        codellama_response = state.draft_answer_en or state.last_model_response or ""

        logger = getattr(runtime, "logger", None)
        log_fn = getattr(logger, "log_interaction", None)

        if callable(log_fn):
            # Prefer the "ports" logger signature if available, fall back to legacy kwargs.
            try:
                log_fn(
                    session_id=state.session_id,
                    pipeline_name="",
                    step_id=step.id,
                    action=step.action,
                    data={
                        "original_question": state.user_query,
                        "model_input_en": state.model_input_en_or_fallback(),
                        "codellama_response": codellama_response,
                        "followup_query": state.followup_query,
                        "query_type": state.query_type,
                        "final_answer": state.answer_en,
                        "context_blocks": list(state.history_blocks) + list(state.context_blocks),
                        "next_codellama_prompt": state.next_codellama_prompt,
                    },
                )
            except TypeError:
                try:
                    log_fn(
                        original_question=state.user_query,
                        model_input_en=state.model_input_en_or_fallback(),
                        codellama_response=codellama_response,
                        followup_query=state.followup_query,
                        query_type=state.query_type,
                        final_answer=state.answer_en,
                        context_blocks=list(state.history_blocks) + list(state.context_blocks),
                        next_codellama_prompt=state.next_codellama_prompt,
                    )
                except TypeError:
                    pass


        # Persist final answer in history (best-effort)
        try:
            runtime.history_manager.set_final_answer(state.answer_en or "", state.answer_pl)
        except Exception:
            pass

        return None
