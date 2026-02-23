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
        sid = str(step.id or "").strip()
        counters = getattr(state, "loop_counters", {}) or {}
        cur = int(counters.get(sid, 0)) if isinstance(counters, dict) else 0
        return {
            "loop_counter_before": cur,
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
        sid = str(step.id or "").strip()
        counters = getattr(state, "loop_counters", {}) or {}
        cur = int(counters.get(sid, 0)) if isinstance(counters, dict) else 0
        return {
            "next_step_id": next_step_id,
            "loop_counter_after": cur,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}
        max_turns = int(settings.get("max_turn_loops", 4))

        sid = str(step.id or "").strip()
        if not sid:
            raise ValueError("loop_guard: step.id is required")

        if not hasattr(state, "loop_counters") or not isinstance(getattr(state, "loop_counters"), dict):
            setattr(state, "loop_counters", {})
        counters: dict = getattr(state, "loop_counters")
        cur = int(counters.get(sid, 0) or 0)

        if cur < max_turns:
            counters[sid] = cur + 1
            return step.raw.get("on_allow")
        return step.raw.get("on_deny")
