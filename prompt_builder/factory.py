from __future__ import annotations

import os
from typing import Optional

from .base import BasePromptBuilder, PromptRenderer
from .codellama import CodellamaPromptBuilder
from .deepseek import DeepSeekPromptBuilder


def get_prompt_builder(model_path: str) -> BasePromptBuilder:
    """
    Factory recognizing model type from path:
    - .../codeLlama... or .../llama... -> CodellamaPromptBuilder
    - .../deepseek... -> DeepSeekPromptBuilder
    """
    normalized_path = str(model_path).lower().replace("\\", "/")

    if "deepseek" in normalized_path:
        return DeepSeekPromptBuilder()

    # default: codellama/llama
    return CodellamaPromptBuilder()


class FileProfilePromptRenderer(PromptRenderer):
    """
    Loads template from prompts_dir/<profile>.txt if exists.
    Falls back to builder default template if missing.
    """

    def __init__(
        self,
        *,
        builder: BasePromptBuilder,
        prompts_dir: str = "prompts",
        system_prompt: str = "",
    ) -> None:
        self._builder = builder
        self._prompts_dir = prompts_dir
        self._system_prompt = system_prompt or ""

    def _try_load_template(self, profile: str) -> Optional[str]:
        fname = f"{profile}.txt"
        path = os.path.join(self._prompts_dir, fname)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def render(
        self,
        *,
        profile: str,
        context: str,
        question: str,
        history: str = "",
    ) -> str:
        template = self._try_load_template(profile)
        return self._builder.build_prompt(
            context=context,
            question=question,
            profile=profile,
            history=history,
            system_prompt=self._system_prompt,
            template=template,
        )


class PromptRendererFactory:
    @staticmethod
    def create(
        *,
        model_path: str,
        prompts_dir: str = "prompts",
        system_prompt: str = "",
    ) -> PromptRenderer:
        builder = get_prompt_builder(model_path)
        return FileProfilePromptRenderer(
            builder=builder,
            prompts_dir=prompts_dir,
            system_prompt=system_prompt,
        )
