# prompt_builder/factory.py
from __future__ import annotations

import os
from typing import Optional, Sequence, Tuple

from code_query_engine.chat_types import Dialog

from .base import BasePromptBuilder, PromptRenderer
from .codellama import CodellamaPromptBuilder
from .deepseek import DeepSeekPromptBuilder


def get_prompt_builder(model_path: str) -> BasePromptBuilder:
    """
    Factory recognizing model type from path:
    - .../codellama... or .../llama... -> CodellamaPromptBuilder
    - .../deepseek... -> DeepSeekPromptBuilder

    NOTE:
    All builders returned here must implement the BasePromptBuilder contract
    (modelFormatedText + history pairs + system_prompt).
    """
    normalized_path = str(model_path).lower().replace("\\", "/")

    if "deepseek" in normalized_path:
        return DeepSeekPromptBuilder()

    # default: codellama/llama
    return CodellamaPromptBuilder()


def get_prompt_builder_by_prompt_format(prompt_format: str) -> BasePromptBuilder:
    """
    Factory selecting a prompt builder by explicit prompt_format.

    This is used by call_model when native_chat/chat_mode is disabled and we build a manual prompt string.
    Unknown prompt_format must fail-fast here (NOT inside call_model), so adding support for a new model
    requires only updating this factory.
    """
    fmt = str(prompt_format or "").strip()
    if fmt == "codellama_inst_7_34":
        return CodellamaPromptBuilder()

    # Future extension point:
    # if fmt == "<your_new_format>":
    #     return YourNewPromptBuilder()

    supported = ["codellama_inst_7_34"]
    raise ValueError(
        f"prompt_builder: no prompt builder implementation for prompt_format '{prompt_format}'. "
        f"Supported prompt_format values: {', '.join(supported)}"
    )


class FileProfilePromptRenderer(PromptRenderer):
    """
    Profile-aware prompt renderer.

    Contract:
    - prompts_dir/<profile>.txt is treated as additional SYSTEM content
      (inserted verbatim by the builder as part of system_prompt).
    - modelFormatedText is built by the pipeline step (call_model) and passed in as-is.
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
        modelFormatedText: str,
        history: Dialog
    ) -> str:
        profile_text = self._try_load_profile_text(profile) or ""

        # System part = pipeline_settings.system_prompt + "\n\n" + profile file (verbatim)
        # NOTE: profile file text must be included without modifications.
        sys_text = (self._system_prompt or "").strip()
        if profile_text:
            sys_text = (sys_text + "\n\n" + profile_text) if sys_text else profile_text

        return self._builder.build_prompt(
            modelFormatedText=str(modelFormatedText),
            history=history,
            system_prompt=sys_text,
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
