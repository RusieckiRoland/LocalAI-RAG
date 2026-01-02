# File: code_query_engine/pipeline/actions/call_model.py

from __future__ import annotations

from typing import Optional, Any, Dict

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from .base_action import PipelineActionBase


class CallModelAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "call_model"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        prompt_key = (raw.get("prompt_key") or "").strip()
        consultant_for_prompt = prompt_key or state.consultant

        history_context = state.history_for_prompt()
        model_input_en = state.model_input_en_or_fallback()

        # This must match what do_execute sends to the model (same stripping + join rules).
        prompt = "\n\n".join([p for p in [history_context.strip(), model_input_en.strip()] if p])

        return {
            "prompt_key": prompt_key,
            "consultant_for_prompt": consultant_for_prompt,
            # Final prompt string passed into runtime.main_model.ask(prompt=...)
            "prompt": prompt,
            # Extra debug: prompt parts
            "history_context": history_context,
            "model_input_en": model_input_en,
            "prompt_parts": {
                "history_context": history_context,
                "model_input_en": model_input_en,
            },
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
            "last_model_response": state.last_model_response,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        prompt_key = (raw.get("prompt_key") or "").strip()
        consultant_for_prompt = prompt_key or state.consultant

        history_context = state.history_for_prompt()
        model_input_en = state.model_input_en_or_fallback()

        state.next_codellama_prompt = consultant_for_prompt

        prompt = "\n\n".join([p for p in [history_context.strip(), model_input_en.strip()] if p])

        # Prefer the new IModelClient API (prompt-based),
        # but remain backward-compatible with the legacy Model.ask(context, question, consultant).
        try:
            response = runtime.main_model.ask(
                prompt=prompt,
                consultant=consultant_for_prompt,
            )
        except TypeError:
            response = runtime.main_model.ask(
                context=history_context,
                question=model_input_en,
                consultant=consultant_for_prompt,
            )

        state.last_model_response = response

        return None
