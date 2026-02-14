from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Tuple

from .contracts import iter_lines_keepends


@dataclass(frozen=True)
class MdLine:
    raw: str  # includes original newline if present
    kind: str  # "fenced_code" | "indented_code" | "html_block" | "normal"


def segment_markdown_lines(md: str) -> List[MdLine]:
    """
    Line-based segmenter focused on preserving original formatting byte-for-byte.
    It identifies fenced code blocks and indented code lines as non-translatable.
    """
    out: List[MdLine] = []
    fence: Optional[str] = None  # "```" or "~~~"

    for line in iter_lines_keepends(md):
        stripped = line.lstrip()

        if fence is not None:
            out.append(MdLine(raw=line, kind="fenced_code"))
            if stripped.startswith(fence):
                fence = None
            continue

        # Start of fenced code block
        if stripped.startswith("```"):
            fence = "```"
            out.append(MdLine(raw=line, kind="fenced_code"))
            continue
        if stripped.startswith("~~~"):
            fence = "~~~"
            out.append(MdLine(raw=line, kind="fenced_code"))
            continue

        # Indented code block line (4 spaces or 1 tab) - treat as code.
        if line.startswith("    ") or line.startswith("\t"):
            out.append(MdLine(raw=line, kind="indented_code"))
            continue

        # Best-effort HTML block: if line starts with '<' and looks like a tag, keep as-is.
        if stripped.startswith("<") and stripped.rstrip().endswith(">"):
            out.append(MdLine(raw=line, kind="html_block"))
            continue

        out.append(MdLine(raw=line, kind="normal"))

    return out
