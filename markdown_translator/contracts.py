from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence


class ITextTranslator(Protocol):
    def translate(self, text: str) -> str:
        ...


class ITextTranslatorBatch(Protocol):
    def translate_many(self, texts: Sequence[str]) -> list[str]:
        ...


@dataclass(frozen=True)
class TranslationResult:
    text: str
    used_templates: int = 0
    translated_chunks: int = 0
    cache_hits: int = 0


def iter_lines_keepends(text: str) -> Iterable[str]:
    # splitlines(keepends=True) keeps original \n/\r\n and trailing newline.
    return text.splitlines(keepends=True)
