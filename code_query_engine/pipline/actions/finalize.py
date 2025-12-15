# code_query_engine/pipeline/actions/finalize.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class FinalizeAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        answer = state.answer_en or "Error: No valid response generated."

        # Translate only when requested and not for UML consultant
        if state.translate_chat and (state.consultant != runtime.constants.UML_CONSULTANT):
            try:
                state.answer_pl = runtime.markdown_translator.translate_markdown(answer)
                state.final_answer = state.answer_pl
            except Exception:
                state.final_answer = answer
        else:
            state.final_answer = answer

        # PlantUML link
        try:
            state.final_answer = runtime.add_plant_link(state.final_answer, state.consultant)
        except Exception:
            pass

        return None
