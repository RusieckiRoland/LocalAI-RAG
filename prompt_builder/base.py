from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BasePromptBuilder(ABC):
    """
    Model-specific prompt builder (e.g. CodeLlama, DeepSeek).
    This class is responsible for:
      - formatting the final prompt string
      - escaping model control tokens inside user-controlled payload
    """

    @abstractmethod
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
        raise NotImplementedError


class PromptRenderer(ABC):
    """
    Profile-aware renderer that:
      - loads a prompt template for a given profile
      - feeds it into a BasePromptBuilder
    """

    @abstractmethod
    def render(
        self,
        *,
        profile: str,
        context: str,
        question: str,
        history: str = "",
    ) -> str:
        raise NotImplementedError
