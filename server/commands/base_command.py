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
    requires_sanitized_answer: bool = False

    def can_execute(self, state: PipelineState) -> bool:
        allowed = getattr(state, "allowed_commands", None)
        if not isinstance(allowed, list):
            return False
        return self.required_permission in allowed

    def build_link(self, answer_text: str, state: PipelineState) -> Optional[str]:
        """
        Build a single HTML link snippet. Return None if not applicable.
        """
        return None

    def _lang(self, state: PipelineState) -> str:
        return "pl" if bool(getattr(state, "translate_chat", False)) else "en"
