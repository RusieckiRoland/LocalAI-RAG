from __future__ import annotations

from functools import lru_cache
import re
from typing import Optional, Tuple

from .contracts import ITextTranslator, ITextTranslatorBatch, TranslationResult
from .segmenter import segment_markdown_lines
from .templates import TemplateRule, TemplatesConfig, apply_templates_to_line, default_templates_path, load_templates_config
from .protect import (
    normalize_placeholder_spacing,
    protect_codeish_tokens,
    protect_inline_code,
    protect_md_links,
    protect_never_translate_terms,
    protect_urls,
    restore_placeholders,
)

_HR_RE = re.compile(r"^\s{0,3}(?:---|\*\*\*|___)\s*$")
_SOURCE_RE = re.compile(r"^\s*(Source:|Źródło:)\s*")
_HEADING_RE = re.compile(r"^(\s{0,3}#{1,6}\s+)(.*)$")
_BLOCKQUOTE_RE = re.compile(r"^(\s{0,3}(?:>\s*)+)(.*)$")
_LIST_RE = re.compile(r"^(\s{0,3}(?:[-*+]|\d+[.)])\s+)(.*)$")


class MarkdownToPolishTranslator:
    """
    Markdown EN → PL translator that preserves Markdown tokenization/formatting without mdpo.

    Key properties:
    - Preserves original line breaks and indentation (no reflow).
    - Never translates fenced/indented code blocks.
    - Protects inline code, URLs, link destinations, and configurable technical terms.
    - Supports deterministic templates (JSON) for phrases that must always translate the same way.
    """

    def __init__(
        self,
        *,
        translator: ITextTranslator,
        templates_path: Optional[str] = None,
        enable_cache: bool = True,
        max_cache_size: int = 2048,
    ) -> None:
        self._translator = translator
        self._templates_cfg: TemplatesConfig = load_templates_config(templates_path or default_templates_path())

        # Instance-level cache (keeps translator state isolated per app instance).
        if enable_cache:
            cached = lru_cache(maxsize=max_cache_size)(self._translate_once)  # type: ignore[arg-type]

            def _wrapped(text: str) -> str:
                before = self._cache_hits
                # lru_cache won't expose hit/miss to us directly; approximate by checking cache_info deltas.
                info_before = cached.cache_info()
                out = cached(text)
                info_after = cached.cache_info()
                if info_after.hits > info_before.hits:
                    self._cache_hits = before + 1
                return out

            self._translate_cached = _wrapped  # type: ignore[assignment]
        else:
            self._translate_cached = self._translate_once  # type: ignore[assignment]

        self._cache_hits = 0

    # --- Public API expected by PipelineRuntime.markdown_translator -----------

    def translate_markdown(self, markdown_en: str) -> str:
        return self.translate(markdown_en).text

    def translate(self, markdown_en: str) -> TranslationResult:
        if not (markdown_en or "").strip():
            return TranslationResult(text=markdown_en or "", used_templates=0, translated_chunks=0, cache_hits=0)

        used_templates = 0
        translated_chunks = 0

        lines = segment_markdown_lines(markdown_en)
        out_parts: list[str] = []

        for mdline in lines:
            if mdline.kind != "normal":
                out_parts.append(mdline.raw)
                continue

            line = mdline.raw
            # Keep exact line ending; operate on body only.
            body, ending = _split_line_ending(line)

            # Preserve empty lines exactly (do not send them to the MT model).
            if body == "":
                out_parts.append(body + ending)
                continue

            # Preserve Markdown horizontal rules and explicit Source lines.
            if _HR_RE.match(body) or _SOURCE_RE.match(body):
                out_parts.append(body + ending)
                continue

            # 1) Deterministic templates (line-level, no translator call).
            templated, matched_rule = apply_templates_to_line(body, self._templates_cfg)
            if matched_rule is not None:
                used_templates += 1
                if matched_rule.match == "exact":
                    out_parts.append(templated + ending)
                    continue

                # prefix template: keep the translated prefix deterministic, but still translate the remainder
                fixed_prefix = matched_rule.pl
                remainder = body[len(matched_rule.en) :]
                if remainder == "":
                    out_parts.append(fixed_prefix + ending)
                    continue

                lead_r, core_r, trail_r = _split_surrounding_ws(remainder)
                if not core_r.strip():
                    out_parts.append(fixed_prefix + remainder + ending)
                    continue

                mapping_r: dict[str, str] = {}
                protected_r = core_r
                protected_r = protect_md_links(protected_r, mapping_r)
                protected_r = protect_urls(protected_r, mapping_r)
                protected_r = protect_inline_code(protected_r, mapping_r)
                protected_r = protect_never_translate_terms(protected_r, mapping_r, self._templates_cfg.never_translate_terms)
                protected_r = protect_codeish_tokens(protected_r, mapping_r)

                translated_r = self._translate_cached(protected_r)
                translated_chunks += 1
                translated_r = normalize_placeholder_spacing(translated_r)
                restored_r = restore_placeholders(translated_r, mapping_r)

                out_parts.append(fixed_prefix + lead_r + restored_r + trail_r + ending)
                continue

            prefix, content = _split_markdown_prefix(templated)
            if not content.strip():
                out_parts.append(templated + ending)
                continue

            lead, core, trail = _split_surrounding_ws(content)
            if not core.strip():
                out_parts.append(templated + ending)
                continue

            # 2) Protect non-translatable regions inside the line.
            mapping: dict[str, str] = {}
            protected = core
            protected = protect_md_links(protected, mapping)
            protected = protect_urls(protected, mapping)
            protected = protect_inline_code(protected, mapping)
            protected = protect_never_translate_terms(protected, mapping, self._templates_cfg.never_translate_terms)
            protected = protect_codeish_tokens(protected, mapping)

            # 3) Translate the remaining text.
            translated = self._translate_cached(protected)
            translated_chunks += 1

            # 4) Undo placeholder damage + restore.
            translated = normalize_placeholder_spacing(translated)
            restored = restore_placeholders(translated, mapping)

            out_parts.append(prefix + lead + restored + trail + ending)

        return TranslationResult(
            text="".join(out_parts),
            used_templates=used_templates,
            translated_chunks=translated_chunks,
            cache_hits=self._cache_hits,
        )

    # --- Internals ------------------------------------------------------------

    def _translate_once(self, text: str) -> str:
        return self._call_translator(text)

    def _call_translator(self, text: str) -> str:
        t = self._translator
        fn_many = getattr(t, "translate_many", None)
        if callable(fn_many):
            # Prefer batch interface if available (single item, but allows optimized impls).
            try:
                out = fn_many([text])
                if isinstance(out, list) and out:
                    return str(out[0])
            except Exception:
                pass
        return str(t.translate(text))


def _split_line_ending(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _split_markdown_prefix(line_body: str) -> Tuple[str, str]:
    m = _BLOCKQUOTE_RE.match(line_body)
    if m:
        return m.group(1), m.group(2)

    m = _HEADING_RE.match(line_body)
    if m:
        return m.group(1), m.group(2)

    m = _LIST_RE.match(line_body)
    if m:
        return m.group(1), m.group(2)

    return "", line_body


def _split_surrounding_ws(s: str) -> Tuple[str, str, str]:
    if not s:
        return "", "", ""
    left = len(s) - len(s.lstrip(" \t"))
    right = len(s) - len(s.rstrip(" \t"))
    return s[:left], s[left : len(s) - right], s[len(s) - right :]
