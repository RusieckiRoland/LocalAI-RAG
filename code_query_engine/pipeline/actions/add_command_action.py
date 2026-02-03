from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.commands import build_default_command_registry

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


_COMMAND_REGISTRY = build_default_command_registry()


class AddCommandAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "add_command_action"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {
            "commands": self._extract_command_types(step),
            "allowed_commands": list(getattr(state, "allowed_commands", []) or []),
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
            "applied": list(getattr(state, "_commands_applied", []) or []),
            "next_step_id": next_step_id,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        types = self._extract_command_types(step)
        if not types:
            return None

        applied: List[str] = []
        for t in types:
            try:
                cmd = _COMMAND_REGISTRY.get(t)
            except KeyError:
                continue

            if not cmd.can_execute(state):
                continue

            state.answer_pl = self._apply_to_text(state.answer_pl, cmd, state, applied)
            state.answer_en = self._apply_to_text(state.answer_en, cmd, state, applied)
            if state.final_answer:
                state.final_answer = self._apply_to_text(state.final_answer, cmd, state, applied)

        if applied:
            setattr(state, "_commands_applied", applied)

        return None

    def _apply_to_text(self, text: Optional[str], cmd, state: PipelineState, applied: List[str]) -> Optional[str]:
        if not text:
            return text
        result = cmd.apply(text, state)
        if result.appended and cmd.command_type not in applied:
            applied.append(cmd.command_type)
        return result.output

    def _extract_command_types(self, step: StepDef) -> List[str]:
        raw = step.raw or {}
        commands = raw.get("commands")
        if not isinstance(commands, list):
            return []

        out: List[str] = []
        for item in commands:
            if isinstance(item, str):
                t = item.strip()
            elif isinstance(item, dict):
                t = str(item.get("type") or "").strip()
            else:
                t = ""
            if t:
                out.append(t)
        return out
