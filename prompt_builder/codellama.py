# prompt_builder/codellama.py
from __future__ import annotations

from typing import Optional, Sequence, Tuple, Any, List

from .base import BasePromptBuilder


class CodellamaPromptBuilder(BasePromptBuilder):
    """
    CodeLlama prompt builder (Llama-2 style chat template).

    Contract:
    - system_prompt is repository-controlled (inserted without escaping),
      but it is embedded into the FIRST user message (as in the official template).
      If there is no history, system_prompt is embedded into the current (final) user message.
    - history is a sequence of (user, assistant) pairs (previous completed turns).
    - modelFormatedText is the CURRENT user message payload already composed by the pipeline
      (e.g., it may include RAG evidence + question, formatted exactly as desired).

    Security hardening:
    - Escape template control tokens in all user-controlled text (history and modelFormatedText).
    - Escape braces to avoid accidental .format injection in callers.
    """

    BOS = "<s>"
    EOS = "</s>"

    B_INST = "[INST]"
    E_INST = "[/INST]"
    B_SYS = "<<SYS>>"
    E_SYS = "<</SYS>>"

    def _escape_control_tokens(self, text: str) -> str:
        # Escape template control tokens in user-controlled payload.
        out = text or ""
        # Order matters: escape closing first.
        out = out.replace(self.E_INST, "[/I N S T]")
        out = out.replace(self.B_INST, "[I N S T]")
        out = out.replace(self.B_SYS, "< <SYS> >")
        out = out.replace(self.E_SYS, "< </SYS> >")

        # Also neutralize BOS/EOS markers if the user tries to inject them.
        out = out.replace(self.BOS, "< s >")
        out = out.replace(self.EOS, "< /s >")
        return out

    def _escape_braces(self, text: str) -> str:
        # Avoid .format injection via braces in user-controlled data
        # (even though we do not .format here).
        return (text or "").replace("{", "{{").replace("}", "}}")

    def _eval_text(self, v: Any) -> str:
        # Defensive: callers should pass strings, but we harden against callables.
        if callable(v):
            v = v()
        return str(v or "")

    def _normalize_history(
        self, history: Optional[Sequence[Tuple[Any, Any]]]
    ) -> List[Tuple[str, str]]:
        if not history:
            return []

        out: List[Tuple[str, str]] = []
        for item in history:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise TypeError(
                    "history must be a sequence of 2-tuples: (user_text, assistant_text)"
                )
            u = self._eval_text(item[0])
            a = self._eval_text(item[1])
            out.append((u, a))
        return out

    def build_prompt(
        self,
        modelFormatedText: str,
        history: Optional[Sequence[Tuple[str, str]]] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        # Normalize inputs early (prevents '<bound method ...>' in prompt).
        modelFormatedText = self._eval_text(modelFormatedText)
        hist = self._normalize_history(history)

        # SYSTEM is repository-controlled -> insert as-is (no escaping).
        sp = str(system_prompt or "").strip()

        def _attach_system_if_needed(user_text: str, need_system: bool) -> str:
            if not need_system or not sp:
                return user_text
            return f"{self.B_SYS}\n{sp}\n{self.E_SYS}\n\n{user_text}"

        parts: List[str] = []

        # If we have history, system goes into the first user turn (matches producer template).
        system_attached = False

        for i, (u_raw, a_raw) in enumerate(hist):
            u = u_raw.strip()
            a = a_raw.strip()

            safe_u = self._escape_braces(self._escape_control_tokens(u))
            if not system_attached:
                safe_u = _attach_system_if_needed(safe_u, need_system=True)
                system_attached = True            
           
            safe_a = self._escape_braces(self._escape_control_tokens(a))

            # History turns are complete: <s>[INST] user [/INST] assistant </s>
            parts.append(
                f"{self.BOS}{self.B_INST} {safe_u} {self.E_INST} {safe_a} {self.EOS}"
            )

        # Final/current user message:
        final_user = modelFormatedText.strip()

        # If there was no history, attach SYSTEM to the current message.
        safe_final = self._escape_braces(self._escape_control_tokens(final_user))
        if not system_attached:
            safe_final = _attach_system_if_needed(safe_final, need_system=True)        

        # The last message must be from user, without closing </s>, so the model generates the assistant.
        parts.append(f"{self.BOS}{self.B_INST}\n{safe_final}\n{self.E_INST}")

        return "\n".join(parts)
