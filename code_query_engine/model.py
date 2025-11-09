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

            return output or ""
        except Exception as e:
            logger.warning("Error during LLM call: %s", e, exc_info=False)
            return "[ERROR: Response suppressed due to suspected hallucination or runtime failure.]"

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    @staticmethod
    def _looks_like_hallucination(text: str) -> bool:
        """
        Simple pattern-based guard; tune as needed.
        Returns True if any suspicious pattern appears excessively.
        """
        suspicious_phrases = [
            "TransactionErrorTransaction",
            "ErrorTransactionError",
            "TransactionErrorTransactionErrorTransaction",
        ]
        return any(text.count(p) > 5 for p in suspicious_phrases)

    def _create_llama(self, model_path: str) -> Llama:
        """
        Try to initialize a GPU-backed model first; if it fails,
        retry with a conservative CPU config.
        """
        primary_kwargs: Dict[str, Any] = {
            "model_path": model_path,
            "n_gpu_layers": 40,
            "n_batch": 512,
            "n_ctx": 9000,
            "verbose": False,
            # The following flags may be build-dependent in llama.cpp:
            "low_vram": True,
            "chat_mode": False,
            "flash_attn": True,
            "offload_kqv": True,
        }

        try:
            logger.info("Loading llama model (GPU-first): %s", model_path)
            return Llama(**primary_kwargs)
        except Exception as gpu_err:
            logger.warning("GPU init failed (%s). Falling back to CPU.", gpu_err)

        # CPU fallback (trim to broadly-supported arguments)
        cpu_kwargs: Dict[str, Any] = {
            "model_path": model_path,
            "n_gpu_layers": 0,
            "n_batch": 256,
            "n_ctx": 4096,
            "verbose": False,
        }
        try:
            return Llama(**cpu_kwargs)
        except Exception as cpu_err:
            # Re-raise with clearer context; caller will handle the error path
            logger.error("CPU init failed: %s", cpu_err)
            raise
