from __future__ import annotations

from typing import Optional

from .base import BasePromptBuilder


_DEFAULT_TEMPLATE = (
    "### Context:\n{CONTEXT}\n\n"
    "### User:\n{QUESTION}\n"
)

_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Follow the system instructions. "
    "Answer concisely and safely."
)


def _escape_control_tokens(text: str) -> str:
    """
    DeepSeek builder: keep it conservative too.
    We escape the same tokens as CodeLlama to avoid accidental cross-model injection.
    """
    t = text or ""
    t = t.replace("[/INST]", "[/I N S T]")
    t = t.replace("[INST]", "[I N S T]")
    t = t.replace("<<SYS>>", "< <SYS> >")
    t = t.replace("<</SYS>>", "< </SYS> >")
    return t


class DeepSeekPromptBuilder(BasePromptBuilder):
    def build_prompt(
        self,
        context: str,
        question: str,
        *,
        profile: str,
        history: str = "",
        system_prompt: str = "",
        template: Optional[str] = None,
    ) -> str:
        tpl = template or _DEFAULT_TEMPLATE
        safe_context = _escape_control_tokens(context or "")
        safe_question = _escape_control_tokens(question or "")
        safe_history = _escape_control_tokens(history or "")

        user_content = tpl.format(
            CONTEXT=safe_context,
            QUESTION=safe_question,
            HISTORY=safe_history,
        )

        sys_prompt = system_prompt.strip() if system_prompt else _DEFAULT_SYSTEM_PROMPT

        # Simple generic wrapper (DeepSeek variants differ; keep it stable)
        return f"{sys_prompt}\n\n{user_content}"
