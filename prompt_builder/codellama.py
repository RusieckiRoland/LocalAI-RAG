# prompt_builder/codellama.py
from __future__ import annotations

from typing import Optional

import constants
from .base import BasePromptBuilder


class CodellamaPromptBuilder(BasePromptBuilder):
    """
    CodeLlama prompt builder.

    Security note:
    Escapes CodeLlama template control tokens in user-controlled inputs
    (context/question/history) to mitigate template prompt injection.
    """

    # CodeLlama control tokens (must exist; tests rely on single wrapper + single sys block)
    B_INST = "[INST]"
    E_INST = "[/INST]"
    B_SYS = "<<SYS>>\n"
    E_SYS = "\n<</SYS>>"

    def _load_and_prepare_profile(self, profile: str) -> str:
        """
        Real implementation may load profiles from disk.
        Security tests monkeypatch this method for determinism.
        """
        return ""

    def _inject_required_prefix_constants(self, system_prompt: str) -> str:
        return (
            (system_prompt or "")
            .replace("{ANSWER_PREFIX}", constants.ANSWER_PREFIX)
            .replace("{FOLLOWUP_PREFIX}", constants.FOLLOWUP_PREFIX)
        )

    def _escape_control_tokens(self, text: str) -> str:
        # Escape template control tokens in user-controlled payload.
        out = text or ""
        # Order matters: escape closing first.
        out = out.replace("[/INST]", "[/I N S T]")
        out = out.replace("[INST]", "[I N S T]")
        out = out.replace("<<SYS>>", "< <SYS> >")
        out = out.replace("<</SYS>>", "< </SYS> >")
        return out

    def build_prompt(
        self,
        context: str,
        question: str,
        profile: str,
        history: str = "",
        system_prompt: Optional[str] = None,
        template: Optional[str] = None,
    ) -> str:
        # Resolve system prompt
        sp = (system_prompt or "").strip()
        if not sp:
            sp = self._load_and_prepare_profile(profile)

        sp = self._inject_required_prefix_constants(sp)

        # Ensure we keep a single SYS block even if profile contains SYS markers
        sp = sp.replace(self.B_SYS.strip(), "").replace(self.E_SYS.strip(), "").strip()

        # Escape user-controlled content
        safe_context = self._escape_control_tokens(str(context or ""))
        safe_question = self._escape_control_tokens(str(question or ""))
        safe_history = self._escape_control_tokens(str(history or ""))

        # Avoid .format injection via braces in user data
        safe_context = safe_context.replace("{", "{{").replace("}", "}}")
        safe_question = safe_question.replace("{", "{{").replace("}", "}}")
        safe_history = safe_history.replace("{", "{{").replace("}", "}}")

        # Default user template must contain "### Context:\n" (security tests rely on it)
        if template is None or not str(template).strip():
            template = (
                "### Context:\n{context}\n\n"
                "### Question:\n{question}\n\n"
            )
            if safe_history.strip():
                template += "### History:\n{history}\n\n"
            template += "### Answer:\n"

        user_content = str(template).format(
            context=safe_context.strip() or "(none)",
            question=safe_question.strip(),
            history=safe_history.strip(),
            profile=profile,
        )

        sys_block = f"{self.B_SYS}\n{sp}\n{self.E_SYS}\n\n"
        return f"{self.B_INST}{sys_block}{user_content}{self.E_INST}"

