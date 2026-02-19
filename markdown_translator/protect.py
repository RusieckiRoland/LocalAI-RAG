from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


_URL_RE = re.compile(r"https?://[^\s<>\)]+")

# Inline code: handle simple `...` spans (best-effort; fenced code is handled at line-level).
_INLINE_CODE_RE = re.compile(r"(?<!`)`([^`]+?)`(?!`)")

# Rough Markdown link/image syntax: [text](url) and ![alt](url)
_MD_LINK_RE = re.compile(r"(!?\[)([^\]]+?)(\]\()([^\)]+?)(\))")

# Tokens that look "code-ish" (identifiers, namespaces, paths).
_CODEISH_TOKEN_RE = re.compile(
    r"(?x)"
    r"("
    r"[A-Za-z0-9_.]+(?:\\\\[A-Za-z0-9_.]+)+"  # backslash-separated path without drive letter
    r"[A-Za-z_][A-Za-z0-9_]*\([^\)]*\)"          # call(...)
    r"|[A-Za-z_][A-Za-z0-9_]*::[A-Za-z0-9_:]+"   # ns::type
    r"|[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]+"   # dotted
    r"|[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+"     # snake
    r"|[A-Za-z]:\\\\[^\\s]+"                     # Windows path
    r"|/(?:[^\\s/]+/)+[^\\s/]*"                  # Unix-ish path
    r")"
)


@dataclass(frozen=True)
class ProtectedSpan:
    placeholder: str
    original: str


def protect_urls(text: str, mapping: Dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = f"<URL_{len(mapping)}>"
        mapping[key] = m.group(0)
        return key

    return _URL_RE.sub(repl, text)


def protect_inline_code(text: str, mapping: Dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = f"<IC_{len(mapping)}>"
        mapping[key] = m.group(0)  # keep backticks
        return key

    return _INLINE_CODE_RE.sub(repl, text)


def protect_md_links(text: str, mapping: Dict[str, str]) -> str:
    """
    Protect only the URL part of Markdown links/images; visible text remains translatable.
    """

    def repl(m: re.Match[str]) -> str:
        prefix1, visible, prefix2, url, suffix = m.groups()
        key = f"<LURL_{len(mapping)}>"
        mapping[key] = url
        return f"{prefix1}{visible}{prefix2}{key}{suffix}"

    return _MD_LINK_RE.sub(repl, text)


def protect_never_translate_terms(text: str, mapping: Dict[str, str], terms: Sequence[str]) -> str:
    if not terms:
        return text
    # Longer terms first to avoid partial overlaps.
    for term in sorted({t for t in terms if t}, key=len, reverse=True):
        # Whole-word-ish boundary (keep simple; works for "Class", "JSON", etc.).
        pat = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")

        def repl(m: re.Match[str]) -> str:
            key = f"<NT_{len(mapping)}>"
            mapping[key] = m.group(0)
            return key

        text = pat.sub(repl, text)
    return text


def protect_codeish_tokens(text: str, mapping: Dict[str, str]) -> str:
    out_parts: List[str] = []
    last = 0
    for m in _CODEISH_TOKEN_RE.finditer(text):
        s, e = m.span()
        # Do not touch our own placeholders like <URL_0>, <IC_1>, <NT_2>, ...
        if s > 0 and e < len(text) and text[s - 1] == "<" and text[e] == ">":
            continue

        out_parts.append(text[last:s])
        key = f"<CT_{len(mapping)}>"
        mapping[key] = m.group(0)
        out_parts.append(key)
        last = e

    out_parts.append(text[last:])
    return "".join(out_parts)


def restore_placeholders(text: str, mapping: Dict[str, str]) -> str:
    # Deterministic restore: placeholders inserted in order and are unique.
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text


def normalize_placeholder_spacing(text: str) -> str:
    # Some translators may insert spaces inside <...> placeholders: "< IC_1>" -> "<IC_1>"
    text = re.sub(r"<\s*([A-Z]+)_\s*(\d+)\s*>", r"<\1_\2>", text)
    # Some translators drop the closing ">": "<CT_0," -> "<CT_0>,"
    text = re.sub(r"<\s*([A-Z]+)_\s*(\d+)\s*(?=$|[^A-Za-z0-9_>])", r"<\1_\2>", text)
    return text
