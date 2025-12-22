# code_query_engine/pipeline/actions/translate_in_if_needed.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class TranslateInIfNeededAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        tr = runtime.translator_pl_en
        if state.translate_chat and tr is not None and hasattr(tr, "translate"):
            state.user_question_en = tr.translate(state.user_query)
        else:
            state.user_question_en = state.user_query

        return None
