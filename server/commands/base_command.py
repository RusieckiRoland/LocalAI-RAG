from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from code_query_engine.pipeline.state import PipelineState


@dataclass(frozen=True)
class CommandResult:
    appended: bool
    output: str


class BaseCommand:
    """
    Base class for user-visible commands appended to the final answer.
    """

    command_type: str = ""
    required_permission: str = ""

    def can_execute(self, state: PipelineState) -> bool:
        allowed = getattr(state, "allowed_commands", None)
        if not isinstance(allowed, list):
            return False
        return self.required_permission in allowed

    def apply(self, answer_text: str, state: PipelineState) -> CommandResult:
        """
        Apply command to answer text. Returns CommandResult.
        """
        return CommandResult(appended=False, output=answer_text)

    def _lang(self, state: PipelineState) -> str:
        return "pl" if bool(getattr(state, "translate_chat", False)) else "en"
