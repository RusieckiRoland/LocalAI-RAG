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
    Contract (CodeLlama):
    - prompts_dir/<profile>.txt is the SYSTEM content (insert verbatim into <<SYS>> ... <</SYS>>).
    - The USER/lower part is composed by the pipeline step (call_model inputs/prefixes),
      and passed as context/history/question strings to the builder.
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

    def _try_load_profile_text(self, profile: str) -> Optional[str]:
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
        profile_text = self._try_load_profile_text(profile) or ""

        # System part = pipeline_settings.system_prompt + "\n\n" + prompt_key file (verbatim)
        # NOTE: prompt_key file text must be included without modifications.
        sys_text = (self._system_prompt or "").strip()
        if profile_text:
            sys_text = (sys_text + "\n\n" + profile_text) if sys_text else profile_text

        return self._builder.build_prompt(
            context=context,
            question=question,
            profile=profile,
            history=history,
            system_prompt=sys_text,
            template=None,  # profile file is NOT a user template in the new contract
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
