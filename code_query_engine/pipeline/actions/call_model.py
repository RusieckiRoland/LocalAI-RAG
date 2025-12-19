# File: code_query_engine/pipeline/actions/call_model.py

from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class CallModelAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        prompt_key = (raw.get("prompt_key") or "").strip()
        consultant_for_prompt = prompt_key or state.consultant

        context = state.history_for_prompt()
        model_input_en = state.model_input_en_or_fallback()

        state.next_codellama_prompt = consultant_for_prompt

        response = runtime.main_model.ask(
            context=context,
            question=model_input_en,
            consultant=consultant_for_prompt,
        )
        state.last_model_response = response

        return None
