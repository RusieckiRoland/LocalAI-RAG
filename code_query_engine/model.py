from __future__ import annotations

import logging
from typing import Any, Optional

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

    def __init__(self, model_path: str, *, default_max_tokens: int = 1500, n_ctx: int = 4096):
        self.modelPath = model_path  # keep original attribute name for compatibility
        self.default_max_tokens = int(default_max_tokens)
        self.n_ctx = int(n_ctx)
        if self.default_max_tokens <= 0:
            raise ValueError("Model: default_max_tokens must be > 0")
        if self.n_ctx <= 0:
            raise ValueError("Model: n_ctx must be > 0")
        self.llm = self._create_llama(self.modelPath, n_ctx=self.n_ctx)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def ask(
        self,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        repeat_penalty: float = 1.2,
        top_k: int = 40,
        top_p: Optional[float] = None,
    ) -> str:
        if max_tokens is None:
            max_tokens = self.default_max_tokens
        if temperature is None:
            temperature = 0.1

        # Optional: prepend system prompt if your renderer doesn't already include it.
        if system_prompt:
            prompt = f"{system_prompt}\n\n{prompt}"

        try:
            call_kwargs: dict[str, Any] = {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "repeat_penalty": repeat_penalty,
                "top_k": top_k,
            }
            if top_p is not None:
                call_kwargs["top_p"] = top_p  # llama-cpp-python supports top_p

            res = self.llm(**call_kwargs)
            output = (res.get("choices") or [{}])[0].get("text", "").strip()

            if self._looks_like_hallucination(output):
                raise RuntimeError("Detected hallucination or recursive loop in LLM response.")

            return output

        except Exception as e:
            logger.error(f"Model error: {e}")
            return "[MODEL_ERROR]"

    def ask_chat(
        self,
        *,
        prompt: str,
        history: Optional[list[tuple[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        repeat_penalty: float = 1.2,
        top_k: int = 40,
        top_p: Optional[float] = None,
    ) -> str:
        """
        Chat mode:
        - `prompt` is the CURRENT user message content.
          If your pipeline does RAG, it can embed evidence/context inside this string.
        - `history` is a list of (user_message, assistant_message) for previous turns.
          The model does NOT remember history by itself; you must pass it every call.
        """
        if max_tokens is None:
            max_tokens = self.default_max_tokens
        if temperature is None:
            temperature = 0.1

        try:
            messages: list[dict[str, str]] = []

            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            if history:
                for user_msg, assistant_msg in history:
                    messages.append({"role": "user", "content": user_msg})
                    messages.append({"role": "assistant", "content": assistant_msg})

            messages.append({"role": "user", "content": prompt})

            call_kwargs: dict[str, Any] = {
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "repeat_penalty": repeat_penalty,
                "top_k": top_k,
            }
            if top_p is not None:
                call_kwargs["top_p"] = top_p

            res = self.llm.create_chat_completion(**call_kwargs)

            output = (
                (res.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            if self._looks_like_hallucination(output):
                raise RuntimeError("Detected hallucination or recursive loop in LLM response.")

            return output

        except Exception as e:
            logger.error(f"Model chat error: {e}")
            return "[MODEL_ERROR]"

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        repeat_penalty: float = 1.2,
        top_k: int = 40,
        top_p: Optional[float] = None,
    ) -> str:
        """
        Adapter for pipeline call_model contract (text completion).
        """
        return self.ask(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            top_p=top_p,
        )

    def __call__(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return self.generate(prompt=prompt, system_prompt=system_prompt)

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _create_llama(self, model_path: str, *, n_ctx: int) -> Llama:
        """
        Try GPU first, then fall back to CPU if GPU init fails.
        """
        try:
            llm = Llama(
                model_path=model_path,
                n_ctx=int(n_ctx),
                n_threads=8,
                n_gpu_layers=-1,
                verbose=False,
            )
            self._log_gpu_status(llm, requested_layers=-1)
            return llm
        except Exception as gpu_err:
            logger.error(self._red(f"GPU init failed, falling back to CPU. Error: {gpu_err}"))
            llm = Llama(
                model_path=model_path,
                n_ctx=int(n_ctx),
                n_threads=8,
                n_gpu_layers=0,
                verbose=False,
            )
            self._log_gpu_status(llm, requested_layers=0)
            return llm

    def _log_gpu_status(self, llm: Llama, *, requested_layers: int) -> None:
        """
        Best-effort logging of GPU/CPU offload status.
        Logs red warning when running on CPU or partial offload is detected.
        """
        try:
            actual_layers = (
                getattr(llm, "n_gpu_layers", None)
                or getattr(llm, "_n_gpu_layers", None)
                or getattr(getattr(llm, "model", None), "n_gpu_layers", None)
            )
            total_layers = (
                getattr(llm, "n_layers", None)
                or getattr(getattr(llm, "model", None), "n_layers", None)
            )
            if isinstance(actual_layers, int) and actual_layers == 0:
                logger.error(self._red("LLM running on CPU (n_gpu_layers=0)."))
                return
            if isinstance(actual_layers, int) and isinstance(total_layers, int):
                if 0 < actual_layers < total_layers:
                    logger.warning(self._red(
                        f"LLM partial GPU offload: n_gpu_layers={actual_layers}/{total_layers}."
                    ))
                    return
            # Fallback info log if we cannot resolve actual layers
            logger.info(
                "LLM init: requested n_gpu_layers=%s, detected n_gpu_layers=%s, total_layers=%s",
                requested_layers,
                actual_layers,
                total_layers,
            )
        except Exception as e:
            logger.warning("LLM GPU status detection failed: %s", e)

    @staticmethod
    def _red(msg: str) -> str:
        return f"\x1b[31m{msg}\x1b[0m"

    def _looks_like_hallucination(self, text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return False

        if len(t) > 200 and len(set(t.split())) < 10:
            return True

        return False
