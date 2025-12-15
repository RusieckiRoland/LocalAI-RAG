# code_query_engine/pipeline/actions/loop_guard.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class LoopGuardAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}
        max_turns = int(settings.get("max_turn_loops", 4))

        if state.turn_loop_counter < max_turns:
            state.turn_loop_counter += 1
            return step.raw.get("on_allow")
        return step.raw.get("on_deny")
