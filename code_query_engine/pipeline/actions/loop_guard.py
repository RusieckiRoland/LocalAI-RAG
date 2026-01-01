# code_query_engine/pipeline/actions/loop_guard.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from typing import Any, Dict
from .base_action import PipelineActionBase


class LoopGuardAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "loop_guard"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        settings = runtime.pipeline_settings or {}
        return {
            "turn_loop_counter_before": state.turn_loop_counter,
            "max_turn_loops": int(settings.get("max_turn_loops", 4)),
            "on_allow": step.raw.get("on_allow"),
            "on_deny": step.raw.get("on_deny"),
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
            "turn_loop_counter_after": state.turn_loop_counter,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}
        max_turns = int(settings.get("max_turn_loops", 4))

        if state.turn_loop_counter < max_turns:
            state.turn_loop_counter += 1
            return step.raw.get("on_allow")
        return step.raw.get("on_deny")
