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
        key_lower = consultant_for_prompt.lower()

        # Decide which "context" string to pass to the prompt builder.
        # The prompt builder will wrap it into the outer "### Context:" section.
        if "history_summarizer" in key_lower:
            context = state.history_for_prompt()
        elif "context_summarizer" in key_lower:
            context = state.composed_context_for_prompt()
        elif "router" in key_lower:
            context = state.history_for_prompt()
        elif "assessor" in key_lower:
            context = state.assessor_context_for_prompt()
        elif "answerer_markdown" in key_lower:
            context = state.answer_context_for_prompt()
        elif "answer" in key_lower:
            context = state.answer_context_for_prompt()
        else:
            context = state.history_for_prompt()

        model_input_en = state.model_input_en_or_fallback()

        state.next_codellama_prompt = consultant_for_prompt
        response = runtime.main_model.ask(context, model_input_en, consultant_for_prompt)
        state.last_model_response = response

        # Post-processing hooks (no extra YAML action needed).
        if "router" in key_lower:
            state.router_raw = response

        if "history_summarizer" in key_lower:
            state.history_summary = (response or "").strip()
            state.history_blocks = []
            return None

        if "context_summarizer" in key_lower:
            summarized = (response or "").strip()
            state.context_blocks = [summarized] if summarized else []
            return None

        if "answerer_markdown" in key_lower:
            state.draft_answer_en = (response or "").strip()
            return None

        return None
