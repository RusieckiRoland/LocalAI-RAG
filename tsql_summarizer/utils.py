# utils.py — tiny shared helpers & generic regexes (no T-SQL semantics here)
import re

def strip_comments(sql: str) -> str:
    """
    Remove SQL comments:
    - Strip /* ... */ block comments (multi-line).
    - Strip -- line comments (both full-line and inline).
    Then collapse whitespace/newlines to single spaces and trim.
    """
    if not sql:
        return ""
    s = sql

    # Remove /* ... */ (non-greedy, across newlines)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)

    # Remove -- comments (full-line and inline)
    # 1) full line starting with optional spaces then --
    s = re.sub(r"(?m)^\s*--.*?$", "", s)
    # 2) inline -- to end of line
    s = re.sub(r"(?m)--.*?$", "", s)

    # Collapse all whitespace to single spaces
    s = " ".join(s.split())
    return s

def one_line(text: str, maxlen: int = 140) -> str:
    """
    Collapse whitespace to single spaces and trim to a single line.
    If the result is longer than maxlen, cut at the last word boundary
    that fits and append ' …' (space + ellipsis), keeping total length <= maxlen.
    This matches tests like: one_line("First\nSecond", 12) -> "First line …"
    """
    if not text:
        return ""
    line = re.sub(r"\s+", " ", text).strip()
    if len(line) <= maxlen:
        return line

    # We need to keep space+ellipsis (2 chars) at the end.
    allowance = maxlen - 2
    if allowance <= 0:
        # Degenerate case: no room for any text before ' …'; return just ellipsis.
        return "…"

    # Find last space at or before 'allowance'
    cut_at = line.rfind(" ", 0, allowance + 1)
    if cut_at != -1:
        return line[:cut_at] + " …"

    # No space before allowance → hard cut so total length <= maxlen.
    # Keep as many chars as possible before adding ellipsis only (no leading space).
    return line[:allowance] + "…"


def normalize_ws(s: str) -> str:
    """Normalize whitespace: LF endings, single spaces, collapse blank lines."""
    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()

def one_line(text: str, maxlen: int = 140) -> str:
    """
    Collapse whitespace to single spaces and trim to a single line.
    If the result is longer than maxlen, cut at the last word boundary
    that fits and append ' …' (space + ellipsis), keeping total length <= maxlen.
    """
    if not text:
        return ""

    # 1) Zbij wielolinijkowy tekst do jednej linii, pojedyncze spacje
    line = re.sub(r"\s+", " ", text).strip()

    # 2) Mieścimy się? Zwracamy bez zmian
    if len(line) <= maxlen:
        return line

    # 3) Musimy zostawić miejsce na " …" (2 znaki)
    allowance = maxlen - 2
    if allowance <= 0:
        return "…"

    # 4) Szukamy ostatniej spacji <= allowance
    #    (najpierw obetnij zakres, potem rfind na nim — unika off-by-one)
    cut_region = line[:allowance + 1]
    cut_at = cut_region.rfind(" ")

    if cut_at != -1:
        # Ucinamy DO spacji (bez niej) i dodajemy " …"
        return line[:cut_at] + " …"

    # 5) Brak spacji przed allowance → twarde cięcie, ale wciąż <= maxlen
    return line[:allowance] + "…"


def normalize_ident(name: str) -> str:
    """
    Normalize a T-SQL identifier, segment by segment (split on '.').
    Rules per tests:
      - [brackets]  → strip to inner text (no brackets in output)
      - "double"/'single'/`backtick` → convert to [inner]
      - Collapse internal whitespace within each segment
      - Do NOT auto-add brackets for plain segments (even if they contain spaces)
    """
    import re

    s = (name or "").strip()
    if not s:
        return ""

    parts = s.split(".")
    out_parts: list[str] = []

    for p in parts:
        seg = p.strip()
        if not seg:
            out_parts.append(seg)
            continue

        # already [bracketed] → remove brackets (keep inner)
        if seg.startswith("[") and seg.endswith("]"):
            inner = seg[1:-1].strip()
            inner = re.sub(r"\s+", " ", inner)
            out_parts.append(inner)
            continue

        # "quoted" / 'quoted' / `backtick` → convert to [inner]
        if (seg.startswith('"') and seg.endswith('"')) or \
           (seg.startswith("'") and seg.endswith("'")) or \
           (seg.startswith("`") and seg.endswith("`")):
            inner = seg[1:-1]
            inner = re.sub(r"\s+", " ", inner.strip())
            out_parts.append(f"[{inner}]")
            continue

        # plain segment → just normalize whitespace, no extra brackets
        seg = re.sub(r"\s+", " ", seg)
        out_parts.append(seg)

    return ".".join(out_parts)


# Shared regexes/helpers used across modules
TABLE_HINT_RE = re.compile(r"\bWITH\s*\((?:[^)(]|\([^)]*\))*\)", re.I)
TRAILING_BEGIN_RE = re.compile(r"\bBEGIN(\s+TRANSACTION)?\s*$", re.I)

def strip_table_hints(s: str) -> str:
    """Remove table hints e.g. WITH (NOLOCK) from a FROM/JOIN snippet."""
    return TABLE_HINT_RE.sub("", s)

def clean_preview(s: str) -> str:
    """Tidy common trailing artifacts from preview text."""
    if not s:
        return s
    s = TRAILING_BEGIN_RE.sub("", s).rstrip()
    s = re.sub(r"\){2,}$", ")", s)
    return s
