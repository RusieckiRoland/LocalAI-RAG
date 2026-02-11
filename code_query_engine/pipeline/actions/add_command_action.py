from __future__ import annotations

from typing import Any, Dict, List, Optional

from common.utils import sanitize_uml_answer
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

        base_text, field = self._select_base_text(state)
        if not base_text:
            return None

        applied: List[str] = []
        snippets: List[str] = []
        requires_sanitized = False
        for t in types:
            try:
                cmd = _COMMAND_REGISTRY.get(t)
            except KeyError:
                continue

            if not cmd.can_execute(state):
                continue

            link = cmd.build_link(base_text, state)
            if not link:
                continue
            snippets.append(link)
            applied.append(cmd.command_type)
            requires_sanitized = requires_sanitized or bool(getattr(cmd, "requires_sanitized_answer", False))

        if applied:
            setattr(state, "_commands_applied", applied)
        if not snippets:
            return None

        if requires_sanitized:
            base_text = sanitize_uml_answer(base_text)

        links_html = " ".join(snippets)
        appended = f"{base_text}\n\n<div class=\"command-links\">{links_html}</div>"

        self._write_back(state, field, appended)

        return None

    def _select_base_text(self, state: PipelineState) -> tuple[Optional[str], str]:
        if state.final_answer:
            return state.final_answer, "final_answer"
        if state.answer_translated:
            return state.answer_translated, "answer_translated"
        if state.answer_en:
            return state.answer_en, "answer_en"
        if state.last_model_response:
            return state.last_model_response, "last_model_response"
        return None, ""

    def _write_back(self, state: PipelineState, field: str, text: str) -> None:
        if not field:
            return
        setattr(state, field, text)

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
