# code_query_engine/pipeline/actions/finalize_heuristic.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class FinalizeHeuristicAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        if state.answer_en:
            return None

        resp = (state.last_model_response or "").strip()
        if resp.startswith(runtime.constants.ANSWER_PREFIX):
            state.answer_en = resp.replace(runtime.constants.ANSWER_PREFIX, "").strip()
            state.query_type = "direct answer"
            return None

        # Heuristic: accept a non-trivial response as final answer
        if len(resp) > 20:
            state.answer_en = resp
            state.query_type = "direct answer (heuristic)"
        else:
            state.answer_en = "Unrecognized response from model."
            state.query_type = "fallback error"
        return None
