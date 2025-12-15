# code_query_engine/pipeline/actions/translate_in_if_needed.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class TranslateInIfNeededAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        if state.translate_chat:
            state.user_question_en = runtime.translator_pl_en.translate(state.user_query)
        else:
            state.user_question_en = state.user_query
        return None
