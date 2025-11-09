# File: utils.py
from __future__ import annotations

import re
import constants

"""
Utilities for post-processing model outputs:

- Sanitize Markdown that contains PlantUML diagrams:
  * remove inline/outside links the model may append,
  * extract a canonical @startuml … @enduml block, or keep the original text.
- Extract a single follow-up query from a model response that uses a known prefix.
- Parse loose truthy values into booleans.

Notes:
- Keep behavior stable; only comments/docstrings were normalized to English.
"""

# --- Precompiled patterns -----------------------------------------------------

# ```plantuml
FENCE_OPEN  = re.compile(r"^```plantuml\s*$", re.IGNORECASE)
# ```
FENCE_CLOSE = re.compile(r"^```$", re.IGNORECASE)

# @startuml ... @enduml (match body lazily, including newlines)
BOUNDS_RE   = re.compile(r"@startuml\s*(.*?)\s*@enduml", re.IGNORECASE | re.DOTALL)

# Markdown links [text](http(s)://...)
MD_LINK_RE  = re.compile(r"\[[^\]]*\]\(https?://[^\)]*\)")

# Bare http(s) lines (often added by models as references)
HTTP_LINE_RE= re.compile(r"^\(?https?://[^\s)]+.*\)?$", re.MULTILINE)

FOLLOWUP_PREFIX = constants.FOLLOWUP_PREFIX


# --- Generic helpers ----------------------------------------------------------

def parse_bool(val, default: bool = False) -> bool:
    """
    Convert loosely-typed values into a boolean.

    Truthy strings: {"1","true","yes","y","on"} (case-insensitive).
    Numbers: non-zero -> True.
    Booleans: returned as-is.
    Any other type: returns `default`.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "y", "on")
    return default


# --- PlantUML & Markdown sanitation ------------------------------------------

def sanitize_uml_answer(md: str, answer_prefix: str = "[Answer:]") -> str:
    """
    Clean a Markdown answer and normalize PlantUML output.

    Steps:
    1) Strip Markdown links and raw http(s) lines outside code blocks
       (they add noise to diagram previews).
    2) Try to extract valid PlantUML code:
       - Prefer fenced ```plantuml blocks;
       - Fallback to a global @startuml…@enduml match.
    3) If a valid diagram is found, return a canonical section:
          [Answer:]

          ### Diagram
          ```plantuml
          @startuml
          ...
          @enduml
          ```
       Otherwise, return the original Markdown unchanged.
    """
    # Remove links the model may append (outside code they are not needed here)
    md_clean = MD_LINK_RE.sub("", md)
    md_clean = HTTP_LINE_RE.sub("", md_clean).strip()

    code = _extract_plantuml_code(md_clean)
    if not code:
        # No valid UML → keep the original content untouched
        return md

    return (
        f"{answer_prefix}\n\n"
        "### Diagram\n"
        "```plantuml\n"
        f"{code}\n"
        "```"
    )


def _extract_plantuml_code(md: str) -> str | None:
    """
    Return a canonical '@startuml\\n...\\n@enduml' block or None if not found.

    Strategy:
    - First, look for a fenced ```plantuml code block and wrap/normalize it.
    - If not found, search for a global @startuml…@enduml pair anywhere in the text.
    """
    # 1) Try fenced ```plantuml
    lines = md.splitlines()
    in_block = False
    buf = []
    for ln in lines:
        s = ln.rstrip("\n")
        if not in_block:
            if FENCE_OPEN.match(s.strip()):
                in_block = True
            continue
        if FENCE_CLOSE.match(s.strip()):
            break
        buf.append(s)

    if buf:
        body = "\n".join(buf).strip()
        # If bounds exist inside, extract only the inner content; otherwise wrap it
        m = BOUNDS_RE.search(body)
        inner = m.group(1).strip() if m else body
        return f"@startuml\n{inner}\n@enduml"

    # 2) Fallback: global @startuml…@enduml
    m = BOUNDS_RE.search(md)
    if m:
        return f"@startuml\n{m.group(1).strip()}\n@enduml"

    return None


# --- FOLLOWUP extraction ------------------------------------------------------

def extract_followup(response: str) -> str | None:
    """
    Extract a single follow-up query from a model response based on a fixed prefix.

    Rules:
    - Prefer an exact, literal prefix at the beginning of the response.
    - Otherwise, use a safe regex anchored at ^ with `re.escape(prefix)`.
    - Only the **first line** after the prefix is taken (models sometimes add notes below).
    - Strip surrounding quotes/backticks and square brackets.

    Returns the cleaned follow-up string, or None if not present.
    """
    resp = (response or "").strip()

    # 1) Most reliable: literal prefix at the very start
    if resp.startswith(FOLLOWUP_PREFIX):
        raw = resp[len(FOLLOWUP_PREFIX):].strip()
    else:
        # 2) Safe regex with re.escape and ^ anchor
        m = re.search(rf"^{re.escape(FOLLOWUP_PREFIX)}\s*(.+)$", resp, flags=re.DOTALL)
        if not m:
            return None
        raw = m.group(1).strip()

    # Keep only the first line (the model may append comments below)
    raw = raw.splitlines()[0].strip()

    # Remove surrounding symmetric quotes/backticks if present
    if len(raw) >= 2 and raw[0] in "'\"`" and raw[-1] == raw[0]:
        raw = raw[1:-1].strip()

    # Remove surrounding brackets (common stylistic addition)
    raw = raw.strip("[]")

    return raw or None
