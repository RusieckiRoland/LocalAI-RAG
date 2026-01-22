# code_query_engine/pipeline/token_counter.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable, List


@runtime_checkable
class TokenCounter(Protocol):
    """
    Minimal contract required by the pipeline.

    - fetch_node_texts expects: count_tokens(...) OR count(...)
    - check_context_budget expects: count(...)
    We provide both to be safe and explicit.
    """

    def count_tokens(self, text: str) -> int:
        ...

    def count(self, text: str) -> int:
        ...


@runtime_checkable
class LlamaCppTokenizer(Protocol):
    """
    Strict contract for llama-cpp tokenizer interface.

    We intentionally DO NOT support signature variations (no compatibility shims).
    """

    def tokenize(self, text: bytes, add_bos: bool = False) -> List[int]:
        ...


@dataclass(frozen=True)
class LlamaCppTokenCounter(TokenCounter):
    """
    Production token counter backed by llama-cpp tokenizer.
    """

    llama: LlamaCppTokenizer

    def count_tokens(self, text: str) -> int:
        if self.llama is None:
            raise ValueError("LlamaCppTokenCounter: llama is None")

        s = str(text or "")
        b = s.encode("utf-8", errors="ignore")

        # Strict call. If the llama instance does not match the contract -> fail fast.
        tokens = self.llama.tokenize(b, add_bos=False)

        if tokens is None:
            raise ValueError("LlamaCppTokenCounter: tokenizer returned None")

        return int(len(tokens))

    def count(self, text: str) -> int:
        # Alias required by check_context_budget
        return self.count_tokens(text)


def require_token_counter(obj: object) -> TokenCounter:
    """
    Strict validator used by actions/runners.

    No fallbacks:
    - If obj does not implement TokenCounter -> raise.
    """
    if obj is None:
        raise ValueError("token_counter is required and must not be None")

    # TokenCounter is runtime-checkable, but we validate behavior explicitly.
    count_tokens = getattr(obj, "count_tokens", None)
    count = getattr(obj, "count", None)

    if not callable(count_tokens):
        raise ValueError("token_counter must provide callable count_tokens(text: str) -> int")

    if not callable(count):
        raise ValueError("token_counter must provide callable count(text: str) -> int")

    return obj  # type: ignore[return-value]
