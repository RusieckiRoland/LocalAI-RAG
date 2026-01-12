# prompt_builder/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence, Tuple


class BasePromptBuilder(ABC):
    """
    Model-specific prompt builder (e.g. CodeLlama, DeepSeek).

    Responsibility:
    - Format the final prompt string for the model.
    - Escape model control tokens inside user-controlled payload (user text + history).

    Contract (aligned with CodellamaPromptBuilder):
    - system_prompt is repository-controlled (included verbatim),
    - modelFormatedText and history are user-controlled (must be escaped for the target chat template).

    NOTE:
    - PromptRenderer does NOT build modelFormatedText. That is done by the pipeline step (call_model).
    """

    @abstractmethod
    def build_prompt(
        self,
        modelFormatedText: str,
        history: Optional[Sequence[Tuple[str, str]]] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        raise NotImplementedError


class PromptRenderer(ABC):
    """
    Renders a full prompt string using a builder and a profile key.

    Typical behavior:
    - load prompts_dir/<profile>.txt (UTF-8),
    - merge it into system_prompt (verbatim),
    - delegate final formatting to BasePromptBuilder.build_prompt(...).
    """

    @abstractmethod
    def render(
        self,
        *,
        profile: str,
        modelFormatedText: str,
        history: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> str:
        raise NotImplementedError
