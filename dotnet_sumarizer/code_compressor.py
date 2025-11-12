"""
code_compressor.py (neutral, deletion-only)

Deterministic compactor for RAG code chunks.

Goal: cut token usage by shrinking retrieved code to the minimal, high-signal form
before passing it to an LLM. Optimized for C# repositories but language-agnostic.

Design intent (strict):
- Deletion-only. Do not invent or add any content (no reasons, no brace-fixing).
- Keep original code as-is except for: window extraction, comment/region/attribute/usings removal,
  blank-line collapse, deduplication, and token budgets.
- Deterministic ordering by (rank, distance, path length).
"""

from __future__ import annotations
from typing import List, Dict, Optional, Tuple, Set
import re
import hashlib

__all__ = ["compress_chunks"]

# -------------------------
# Token estimation utility
# -------------------------

def _estimate_tokens(text: str) -> int:
    """Estimate token count. Uses tiktoken if available; else char/4 fallback."""
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _trim_to_token_budget(text: str, budget: int) -> str:
    """Approximate trim by tokens, cut at newline boundary to avoid half-lines."""
    if budget <= 0:
        return ""
    if _estimate_tokens(text) <= budget:
        return text
    approx_chars = max(16, budget * 4)
    head = text[:approx_chars]
    # trim to last complete line
    return head.rsplit("\n", 1)[0]


# -------------------------
# Text utilities (C#-friendly)
# -------------------------

_CSHARP_USING_RE = re.compile(r"^\s*using\s+[A-Za-z0-9_.<>]+\s*;\s*$")
_XMLDOC_RE = re.compile(r"^\s*///.*$")
_REGION_RE = re.compile(r"^\s*#(region|endregion).*$")
_PRAGMA_RE = re.compile(r"^\s*#(if|endif|pragma|warning).*$")
_LINE_COMMENT_RE = re.compile(r"//.*$")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_block_comments(text: str) -> str:
    return _BLOCK_COMMENT_RE.sub("", text)


def _strip_line_comments(text: str) -> str:
    """Remove XML doc and // comments; keep http(s):// and string content."""
    out_lines: List[str] = []
    for raw in text.splitlines():
        if _XMLDOC_RE.match(raw):
            continue
        line = raw
        i = 0
        n = len(line)
        in_str = False
        str_ch = ""
        while i < n:
            ch = line[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == str_ch:
                    in_str = False
                i += 1
                continue
            if ch in ('"', "'"):
                in_str = True
                str_ch = ch
                i += 1
                continue
            if ch == "/" and i + 1 < n and line[i + 1] == "/":
                prefix = line[max(0, i - 6):i]
                if prefix.endswith("http:") or prefix.endswith("https:"):
                    i += 2
                    continue
                line = line[:i]
                break
            i += 1
        out_lines.append(line)
    return "\n".join(out_lines)


def _strip_regions_and_pragmas(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not (_REGION_RE.match(l) or _PRAGMA_RE.match(l)))


def _strip_attributes(text: str) -> str:
    """Remove C# attributes like [Something(...)] including multi-line."""
    out_lines: List[str] = []
    in_attr = False
    depth = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not in_attr and line.strip().startswith("["):
            in_attr = True
            depth = line.count("[") - line.count("]")
            if depth <= 0:
                in_attr = False
                continue
            continue
        if in_attr:
            depth += line.count("[") - line.count("]")
            if depth <= 0:
                in_attr = False
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _strip_leading_usings(text: str) -> str:
    """Remove leading using directives."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and _CSHARP_USING_RE.match(lines[i]):
        i += 1
    return "\n".join(lines[i:])


def _collapse_blank_lines(text: str) -> str:
    out: List[str] = []
    blank = False
    for line in text.splitlines():
        s = line.rstrip()
        if s == "":
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(s)
            blank = False
    return "\n".join(out).strip()


# -------------------------
# Windowing
# -------------------------

def _merge_intervals(intervals: List[Tuple[int, int]], join_gap: int = 3) -> List[Tuple[int, int]]:
    if not intervals:
        return []
    intervals.sort()
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ls, le = merged[-1]
        if s <= le + join_gap:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def _extract_windows(code: str, hit_lines: Optional[List[int]], window: int) -> str:
    lines = code.splitlines()
    n = len(lines)
    if not hit_lines:
        return code
    intervals: List[Tuple[int, int]] = []
    for h in hit_lines:
        idx = max(0, min(n - 1, h - 1))
        s = max(0, idx - window)
        e = min(n - 1, idx + window)
        intervals.append((s, e))
    merged = _merge_intervals(intervals)
    snippet = "\n".join("\n".join(lines[s:e + 1]) for s, e in merged)

    # --- Python-specific pre-cleanup: remove leading comments before first code line ---
    stripped_lines = snippet.splitlines()
    cleaned_lines = []
    code_started = False
    for l in stripped_lines:
        stripped = l.strip()
        if not code_started:
            if stripped.startswith("#") or stripped == "":
                continue
            code_started = True
        cleaned_lines.append(l)
    return "\n".join(cleaned_lines)



# -------------------------
# Formatting helpers
# -------------------------

def _header_line(chunk: Dict, prefix: str) -> str:
    path = chunk.get("path") or "<unknown>"
    ns = chunk.get("namespace")
    cls = chunk.get("class")
    mem = chunk.get("member")
    start = chunk.get("start_line")
    end = chunk.get("end_line")

    parts: List[str] = []
    if ns and cls:
        parts.append(f"{ns}.{cls}")
    elif cls:
        parts.append(cls)
    if mem:
        if parts:
            parts[-1] += f".{mem}"
        else:
            parts.append(mem)

    span = f" (L{start}-{end})" if (start and end and start <= end) else ""
    qualified = parts[0] if parts else "<symbol>"
    return f"{prefix}{path} : {qualified}{span}"


# -------------------------
# Cleaning
# -------------------------

def _clean(snippet: str, language: str) -> str:
    lang = language.lower().strip()

    # --- C# cleanup ---
    if lang in {"csharp", "cs", "dotnet", "c#"}:
        snippet = _strip_block_comments(snippet)
        snippet = _strip_line_comments(snippet)
        snippet = _strip_regions_and_pragmas(snippet)
        snippet = _strip_attributes(snippet)
        snippet = _strip_leading_usings(snippet)
        snippet = _collapse_blank_lines(snippet)
        return snippet

    # --- Python cleanup ---
    if lang == "python":
        lines = snippet.splitlines()
        cleaned: list[str] = []
        code_started = False

        for line in lines:
            stripped = line.strip()

            # Skip leading comments and blanks
            if not code_started:
                if stripped.startswith("#") or stripped == "":
                    continue
                code_started = True

            new_line_chars = []
            in_str = False
            str_char = None
            i = 0
            while i < len(line):
                ch = line[i]
                if in_str:
                    new_line_chars.append(ch)
                    # handle escaped quote
                    if ch == "\\" and i + 1 < len(line):
                        new_line_chars.append(line[i + 1])
                        i += 2
                        continue
                    if ch == str_char:
                        in_str = False
                    i += 1
                    continue

                if ch in ("'", '"'):
                    in_str = True
                    str_char = ch
                    new_line_chars.append(ch)
                    i += 1
                    continue

                # comment start only outside strings
                if ch == "#":
                    break

                new_line_chars.append(ch)
                i += 1

            cleaned_line = "".join(new_line_chars).rstrip()
            if cleaned_line.strip():
                cleaned.append(cleaned_line)

        snippet = "\n".join(cleaned)
        return _collapse_blank_lines(snippet)

    # --- Fallback for other languages ---
    snippet = _BLOCK_COMMENT_RE.sub("", snippet)
    snippet = _LINE_COMMENT_RE.sub("", snippet)
    return _collapse_blank_lines(snippet)



def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _sort_key(c: Dict) -> Tuple:
    rank = c.get("rank")
    dist = c.get("distance")
    path = c.get("path") or ""
    return (
        (rank if isinstance(rank, int) else 10_000),
        (dist if isinstance(dist, (int, float)) else 10_000.0),
        len(path),
    )


# -------------------------
# Core compressor
# -------------------------

def compress_chunks(
    chunks: List[Dict],
    *,
    mode: str = "metadata",
    token_budget: int = 1200,
    window: int = 18,
    max_chunks: int = 8,
    language: str = "csharp",
    per_chunk_hard_cap: Optional[int] = None,
    header_prefix: str = "- ",
) -> str:
    """Compress retrieved chunks by deletion-only cleanup.

    Zero-guessing policy:
    - We never trim individual snippets mid-code.
    - A snippet is either included in full (after cleanup) or skipped entirely.
    """
    if not chunks:
        return ""

    mode = mode.lower().strip()
    assert mode in {"metadata", "snippets", "two_stage"}, "Invalid mode"

    seen: Set[object] = set()
    uniq: List[Dict] = []
    for c in sorted(chunks, key=_sort_key):
        if mode in {"metadata", "two_stage"}:
            key = c.get("path")
        else:
            key = (c.get("path"), c.get("member") or c.get("class") or (c.get("start_line"), c.get("end_line")))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    out_lines: List[str] = []
    used_tokens = 0
    snippet_digests: Set[str] = set()

    uniq = uniq[: max(1, max_chunks)]

    for c in uniq:
        prepared_snippet: Optional[str] = None
        digest: Optional[str] = None
        is_dup = False

        if mode == "snippets":
            raw = c.get("content") or ""
            prepared_snippet = _clean(_extract_windows(raw, c.get("hit_lines"), window), language)
            # Zero-guessing: do NOT trim individual snippets here.
            if prepared_snippet.strip():
                digest = _digest(prepared_snippet)
                is_dup = digest in snippet_digests

        header = _header_line(c, header_prefix)
        header_cost = _estimate_tokens(header + "\n")
        if used_tokens + header_cost > token_budget:
            break
        out_lines.append(header)
        used_tokens += header_cost

        if mode in {"metadata", "two_stage"}:
            continue

        snippet = prepared_snippet or _clean(
            _extract_windows(c.get("content") or "", c.get("hit_lines"), window),
            language,
        )
        if not snippet.strip():
            continue
        if is_dup:
            continue

        code_lang = "csharp" if language.lower() in {"csharp", "cs", "c#", "dotnet"} else ""
        fence_open = f"```{code_lang}\n" if code_lang else "```\n"
        code_block = f"{fence_open}{snippet}\n```"
        block_cost = _estimate_tokens(code_block + "\n")

        # Zero-guessing: if full snippet does not fit, do not trim; stop adding code.
        if used_tokens + block_cost > token_budget:
            break

        out_lines.append(code_block)
        used_tokens += block_cost
        if digest:
            snippet_digests.add(digest)

    return "\n".join(out_lines).rstrip() + "\n"
