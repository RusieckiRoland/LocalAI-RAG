from __future__ import annotations

from .base import BasePromptBuilder
import constants


class CodellamaPromptBuilder(BasePromptBuilder):
    """
    CodeLlama-specific builder with proper constants injection.

    Security note:
    This builder escapes CodeLlama template control tokens in user-controlled inputs
    (context/question) to mitigate template prompt-injection such as closing [/INST]
    or injecting a fake <<SYS>> block.
    """

    B_INST = "[INST]"
    E_INST = "[/INST]"
    B_SYS = "<<SYS>>\n"
    E_SYS = "\n<</SYS>>\n\n"

    @property
    def PROFILE_SUFFIX(self) -> str:
        return ""  # No suffix

    def _escape_control_tokens(self, text: str) -> str:
        """
        Escape CodeLlama prompt-template control tokens inside user-controlled text.
        This prevents a user from closing/opening template blocks or injecting sys blocks.
        """
        if not text:
            return text

        return (
            text
            .replace(self.E_INST, "[/I N S T]")
            .replace(self.B_INST, "[I N S T]")
            .replace("<<SYS>>", "< <SYS> >")
            .replace("<</SYS>>", "< </SYS> >")
        )

    def build_prompt(self, context: str, question: str, profile: str = "turing") -> str:
        # Load and inject constants into system prompt (system prompt is trusted).
        system_prompt = self._load_and_prepare_profile(profile)
        system_prompt = (
            system_prompt
            .replace("{ANSWER_PREFIX}", constants.ANSWER_PREFIX)
            .replace("{FOLLOWUP_PREFIX}", constants.FOLLOWUP_PREFIX)
        )

        # Escape user-controlled content to mitigate template injection.
        safe_context = self._escape_control_tokens(context or "")
        safe_question = self._escape_control_tokens(question or "")

        sys_block = self.B_SYS + system_prompt + self.E_SYS
        user_content = (
            f"### Context:\n{safe_context.strip() or '(none)'}\n\n"
            f"### User:\n{safe_question.strip()}\n"
        )

        return f"{self.B_INST}{sys_block}{user_content}{self.E_INST}"
