# code_query_engine/pipeline/actions/call_model.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class CallModelAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        prompt_key = (step.raw.get("prompt_key") or "").strip()
        consultant_for_prompt = prompt_key or state.consultant

        context = state.history_for_prompt()
        # Evidence context is only added for answer prompt (or when explicitly needed).
        # Keep deterministic behavior: the prompt builder decides how it uses context.
        model_input_en = state.model_input_en_or_fallback()

        state.next_codellama_prompt = consultant_for_prompt
        response = runtime.main_model.ask(context, model_input_en, consultant_for_prompt)
        state.last_model_response = response

        # Store router raw too (handy for debugging)
        if "router" in consultant_for_prompt.lower():
            state.router_raw = response

        return None
