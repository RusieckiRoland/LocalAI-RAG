from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from llama_cpp import Llama


logger = logging.getLogger(__name__)


class Model:
    """
    Thin wrapper around llama-cpp.

    Responsibility:
    - Accept a fully built prompt (string),
    - Run a single completion call,
    - Guard against obvious hallucination loops.

    NOTE:
    Prompt construction is NOT done here. It must be done by the pipeline step (call_model).
    """

    def __init__(self, model_path: str):
        self.modelPath = model_path  # keep original attribute name for compatibility
        self.llm = self._create_llama(self.modelPath)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def ask(
        self,
        *,
        prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.1,
        repeat_penalty: float = 1.2,
        top_k: int = 40,
    ) -> str:
        """
        Query the model using a ready prompt.

        Returns
        -------
        str
            Model's text output (trimmed). If a severe error or a suspected
            hallucination loop occurs, a short error marker is returned.
        """
        try:
            res = self.llm(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                repeat_penalty=repeat_penalty,
                top_k=top_k,
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

        if len(t) > 200 and len(set(t.split())) < 10:
            return True

        return False
