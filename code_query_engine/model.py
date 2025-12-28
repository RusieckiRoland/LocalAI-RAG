# File: inference/model.py
from __future__ import annotations

import logging
from typing import Any, Dict

from llama_cpp import Llama
from prompt_builder.factory import get_prompt_builder


logger = logging.getLogger(__name__)


class Model:
    """
    Thin wrapper around llama-cpp to:
      - build prompts via a pluggable prompt builder,
      - run a single completion call,
      - guard against obvious hallucination loops.

    Notes
    -----
    - Default llama parameters mirror your previous setup.
    - A GPU→CPU fallback is attempted if GPU init fails.
    - Some llama-cpp flags (e.g., flash_attn, offload_kqv, low_vram) may be
      version-dependent; if unsupported by your build they are ignored by the
      fallback path.
    """

    def __init__(self, model_path: str):
        self.modelPath = model_path  # keep original attribute name for compatibility
        self.llm = self._create_llama(self.modelPath)
        self.promptBuilder = get_prompt_builder(model_path=self.modelPath)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def ask(self, context: str, question: str, consultant: str) -> str:
        """
        Build a prompt and query the model.

        Returns
        -------
        str
            Model's text output (trimmed). If a severe error or a suspected
            hallucination loop occurs, a short error marker is returned.
        """
        prompt = self.promptBuilder.build_prompt(context, question, consultant)
        try:
            res = self.llm(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.1,
                repeat_penalty=1.2,
                top_k=40,
            )
            output = (res.get("choices") or [{}])[0].get("text", "").strip()

            if self._looks_like_hallucination(output):
                raise RuntimeError("Detected hallucination or recursive loop in LLM response.")

            return output

        except Exception as e:
            logger.error(f"Model error: {e}")
            return "[MODEL_ERROR]"

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _create_llama(self, model_path: str) -> Llama:
        """
        Try GPU first, then fall back to CPU if GPU init fails.
        """
        try:
            return Llama(
                model_path=model_path,
                n_ctx=4096,
                n_threads=8,
                n_gpu_layers=-1,
                verbose=False,
            )
        except Exception as gpu_err:
            logger.warning(f"GPU init failed, falling back to CPU. Error: {gpu_err}")
            return Llama(
                model_path=model_path,
                n_ctx=4096,
                n_threads=8,
                n_gpu_layers=0,
                verbose=False,
            )

    def _looks_like_hallucination(self, text: str) -> bool:
        """
        Very simple loop detection: repeated tokens / obvious recursive patterns.
        """
        t = (text or "").strip().lower()
        if not t:
            return False

        # Common bad patterns:
        # - Same short phrase repeated
        if len(t) > 200 and len(set(t.split())) < 10:
            return True

        return False
