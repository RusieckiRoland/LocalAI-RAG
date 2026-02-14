# File: common/markdown_translator_en_pl.py
from __future__ import annotations

from typing import Optional

from common.translator_pl_en import Translator
from markdown_translator import MarkdownToPolishTranslator


class MarkdownTranslator:
    """
    Translate Markdown EN → PL using a local MarianMT model while preserving formatting.

    This implementation intentionally avoids mdpo/po2md-based roundtrips, which can
    normalize whitespace and break Markdown structure (extra blank lines, reflow).

    Public API contract used by the pipeline:
    - translate_markdown(markdown_en: str) -> str
    - translate(text: str) -> str   (optional fallback)
    """

    def __init__(self, model_path: str, *, templates_path: Optional[str] = None) -> None:
        self._text_translator = Translator(model_path)
        self._md_translator = MarkdownToPolishTranslator(
            translator=self._text_translator,
            templates_path=templates_path,
            enable_cache=True,
        )

    def translate_markdown(self, markdown_en: str) -> str:
        return self._md_translator.translate_markdown(markdown_en)

    def translate(self, text: str) -> str:
        # Conservative: treat plain text as Markdown for consistent protection behavior.
        return self._md_translator.translate_markdown(text)
