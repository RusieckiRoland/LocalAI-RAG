import re
from typing import Dict, Any, List, Tuple

# If you already import strip_comments/normalize_ws elsewhere, reuse them; otherwise copy.
PARENS_WORD_RE = re.compile(r"\(([^\)]*)\)")

def _split_commas_top(s: str) -> List[str]:
    """Split by commas at top level (ignore commas inside parentheses/quotes)."""
    out, buf, lvl, in_sq = [], [], 0, False
    i, n = 0, len(s or "")
    while i < n:
        ch = s[i]
        if ch == "'" and not in_sq:
            in_sq = True; buf.append(ch)
        elif ch == "'" and in_sq:
            in_sq = False; buf.append(ch)
        elif not in_sq:
            if ch == '(':
                lvl += 1; buf.append(ch)
            elif ch == ')':
                lvl = max(0, lvl-1); buf.append(ch)
            elif ch == ',' and lvl == 0:
                out.append("".join(buf).strip()); buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)
        i += 1
    if buf:
        out.append("".join(buf).strip())
    return out

def _balanced_block_after(s: str, start_idx: int) -> Tuple[str, int]:
    """Return text inside the balanced parentheses starting at the first '(' after start_idx,
    and the index just after the closing ')'."""
    i = s.find("(", start_idx)
    if i < 0: return "", start_idx
    lvl, j, n = 1, i + 1, len(s)
    while j < n and lvl > 0:
        if s[j] == '(':
            lvl += 1
        elif s[j] == ')':
            lvl -= 1
        j += 1
    inner = s[i+1:j-1] if lvl == 0 else s[i+1:j]
    return inner, j

def _extract_table_body(sql: str) -> Tuple[str, str]:
    """
    Return (table_name, body_inside_parentheses) for CREATE TABLE ... ( ... ) tail,
    ignoring trailing options like ON [FG].
    """
    m = re.search(r"\bCREATE\s+TABLE\s+([A-Za-z0-9_\.\[\]]+)\s*\(", sql, flags=re.I)
    if not m:
        return "", ""
    tname = m.group(1).strip()
    _, end_hdr = "", m.end() - 1  # position of '('
    body, after = _balanced_block_after(sql, m.start())
    return tname, body

def _normalize_ident(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return name
    if name.startswith("[") and name.endswith("]"):
        return name
    # bare -> bracket
    return f"[{name.strip('[]')}]"

def _strip_brackets(name: str) -> str:
    return (name or "").strip().strip("[]")

def build_table_meta(sql: str) -> Dict[str, Any]:
    """
    Parse a CREATE TABLE statement and return structured metadata:
    - filegroup
    - columns (name, type, nullable, default, rowguidcol/rowversion)
    - primary_key
    - unique_constraints
    - foreign_keys
    - check_constraints
    """

    # ----- helpers (local to keep the patch self-contained) -----
    def _unwrap_parens(expr: str) -> str:
        """Strip redundant outer parentheses: ((0)) -> 0, (N'X') -> N'X'."""
        e = (expr or "").strip()
        while len(e) >= 2 and e[0] == "(" and e[-1] == ")":
            inner = e[1:-1].strip()
            if not inner:
                break
            e = inner
        return e

    def _find_default_expr(tail: str) -> str | None:
        """
        Return the DEFAULT expression string with balanced parentheses.
        Examples:
          DEFAULT (newid())                    -> "newid()"
          DEFAULT ((0))                        -> "0"
          CONSTRAINT DF ... DEFAULT (getdate())-> "getdate()"
          DEFAULT 0                            -> "0"         (no parens form)
        """
        if not tail:
            return None
        m = re.search(r"\bDEFAULT\b", tail, flags=re.I)
        if not m:
            return None
        i = m.end()
        n = len(tail)
        # skip whitespace
        while i < n and tail[i].isspace():
            i += 1
        # parenthesized form
        if i < n and tail[i] == "(":
            lvl = 0
            j = i
            in_sq = False  # handle single quotes inside defaults
            while j < n:
                ch = tail[j]
                if ch == "'" and (j == 0 or tail[j-1] != "'"):
                    in_sq = not in_sq
                if not in_sq:
                    if ch == "(":
                        lvl += 1
                    elif ch == ")":
                        lvl -= 1
                        if lvl == 0:
                            expr = tail[i+1:j].strip()  # inside DEFAULT ( ... )
                            return _unwrap_parens(expr)
                j += 1
            # fallback (unbalanced) – trim whatever is left
            expr = tail[i:].strip()
            return _unwrap_parens(expr)
        # rare: DEFAULT <literal> (without parens)
        j = i
        while j < n and tail[j] not in (",", " ", "\t", "\r", "\n"):
            j += 1
        lit = tail[i:j].strip()
        return _unwrap_parens(lit) if lit else None

    def _parse_key_columns(list_text: str) -> list[str]:
        """
        Normalize a list of columns from '( [Col] ASC, Other DESC )' to ['Col','Other'].
        Strips brackets and ASC/DESC decorations.
        """
        cols_raw = [c for c in (list_text or "").split(",") if c.strip()]
        cols: list[str] = []
        for c in cols_raw:
            c = c.strip()
            m = re.match(r"(?:\[\s*([^\]]+)\s*\]|([A-Za-z_]\w+))(?:\s+ASC|\s+DESC)?\s*$", c, flags=re.I)
            if m:
                name = (m.group(1) or m.group(2) or "").strip()
                cols.append(name)
            else:
                # last resort: drop ASC/DESC and brackets crudely
                name = re.sub(r"\s+(ASC|DESC)\b", "", c, flags=re.I)
                name = name.strip().strip("[]").strip()
                if name:
                    cols.append(name)
        return cols

    # ----- init -----
    meta: Dict[str, Any] = {
        "filegroup": None,
        "columns": [],
        "primary_key": None,
        "unique_constraints": [],
        "foreign_keys": [],
        "check_constraints": []
    }

    # table-level filegroup (after closing ') ... ON [FG_...]')
    mfg = re.search(r"\)\s+ON\s+(\[[^\]]+\]|[A-Za-z0-9_]+)", sql, flags=re.I)
    if mfg:
        meta["filegroup"] = mfg.group(1)

    tname_raw, body = _extract_table_body(sql)
    if not body:
        return meta

    # split body into top-level comma-separated parts (columns + constraints)
    parts = _split_commas_top(body)

    # regex helpers
    re_notnull = re.compile(r"\bNOT\s+NULL\b", re.I)
    re_null    = re.compile(r"\bNULL\b", re.I)
    re_rowguid = re.compile(r"\bROWGUIDCOL\b", re.I)

    # constraints patterns
    re_pk = re.compile(
        r"^(?:CONSTRAINT\s+(\[[^\]]+\]|[A-Za-z_]\w+)\s+)?PRIMARY\s+KEY\s+"
        r"(CLUSTERED|NONCLUSTERED)?\s*\(([^)]+)\)(?:.*?ON\s+(\[[^\]]+\]|[A-Za-z_]\w+))?",
        re.I | re.S
    )
    re_uq = re.compile(
        r"^(?:CONSTRAINT\s+(\[[^\]]+\]|[A-Za-z_]\w+)\s+)?UNIQUE\s+"
        r"(CLUSTERED|NONCLUSTERED)?\s*\(([^)]+)\)",
        re.I | re.S
    )
    re_fk = re.compile(
        r"^(?:CONSTRAINT\s+(\[[^\]]+\]|[A-Za-z_]\w+)\s+)?FOREIGN\s+KEY\s*\(([^)]+)\)\s+"
        r"REFERENCES\s+([A-Za-z0-9_\.\[\]]+)\s*\(([^)]+)\)",
        re.I | re.S
    )
    re_ck = re.compile(
        r"^(?:CONSTRAINT\s+(\[[^\]]+\]|[A-Za-z_]\w+)\s+)?CHECK\s*\(",
        re.I
    )

    for seg in parts:
        s = seg.strip()

        # ----- PRIMARY KEY -----
        mpk = re_pk.match(s)
        if mpk:
            name = mpk.group(1)
            clustered = (mpk.group(2) or "").upper() == "CLUSTERED"
            cols = _parse_key_columns(mpk.group(3) or "")
            meta["primary_key"] = {
                "name": name,
                "clustered": bool(clustered),
                "columns": cols
            }
            continue

        # ----- UNIQUE -----
        muq = re_uq.match(s)
        if muq:
            name = muq.group(1)
            clustered = (muq.group(2) or "").upper() == "CLUSTERED"
            cols = _parse_key_columns(muq.group(3) or "")
            meta["unique_constraints"].append({
                "name": name,
                "clustered": bool(clustered),
                "columns": cols
            })
            continue

        # ----- FOREIGN KEY -----
        mfk = re_fk.match(s)
        if mfk:
            name = mfk.group(1)
            cols = _parse_key_columns(mfk.group(2) or "")
            ref_tab = (mfk.group(3) or "").strip()
            ref_cols = _parse_key_columns(mfk.group(4) or "")
            meta["foreign_keys"].append({
                "name": name,
                "columns": cols,
                "ref_table": ref_tab,
                "ref_columns": ref_cols
            })
            continue

        # ----- CHECK (balanced) -----
        mck = re_ck.match(s)
        if mck:
            # extract balanced expression inside CHECK(...)
            # mck.end() is right after "CHECK(", so pass index at the '(' position
            paren_idx = mck.end() - 1
            expr, _ = _balanced_block_after(s, paren_idx)
            meta["check_constraints"].append({
                "name": mck.group(1),
                "expression": expr.strip()
            })
            continue

        # ----- Column definition (fallback) -----
        # Pattern: [Name] TYPE[(...)] [NULL|NOT NULL] [CONSTRAINT ... DEFAULT(...)] [ROWGUIDCOL]
        mcol = re.match(r"^\s*(\[[^\]]+\]|[A-Za-z_]\w+)\s+(.+)$", s, flags=re.S)
        if not mcol:
            continue

        col_name = _strip_brackets(mcol.group(1))
        tail = mcol.group(2).strip()

        # type = until first of keywords
        kw_positions = []
        for kw in [" NOT NULL", " NULL", " DEFAULT", " CONSTRAINT", " ROWGUIDCOL", " PRIMARY KEY",
                   " UNIQUE", " CHECK", " FOREIGN KEY", " REFERENCES"]:
            p = tail.upper().find(kw)
            if p >= 0:
                kw_positions.append(p)
        cut = min(kw_positions) if kw_positions else len(tail)
        col_type = tail[:cut].strip()

        # nullability (default is nullable unless NOT NULL is present)
        notnull = bool(re_notnull.search(tail))
        null_tok = bool(re_null.search(tail)) and not notnull
        nullable = not notnull
        if notnull:
            nullable = False
        elif null_tok:
            nullable = True

        # default (balanced)
        default_expr = _find_default_expr(tail)

        # flags
        rowguid = bool(re_rowguid.search(tail))
        typu = (col_type or "").upper()
        rowversion = typu.startswith("ROWVERSION") or typu.startswith("TIMESTAMP")

        meta["columns"].append({
            "name": col_name,
            "type": re.sub(r"\s+", " ", col_type),
            "nullable": bool(nullable),
            "default": default_expr,
            "rowguidcol": bool(rowguid),
            "rowversion": bool(rowversion)
        })

    return meta


def _unwrap_parens(expr: str) -> str:
    """Strip redundant outer parentheses: ((0)) -> 0, (N'X') -> N'X'."""
    e = (expr or "").strip()
    while len(e) >= 2 and e[0] == "(" and e[-1] == ")":
        inner = e[1:-1].strip()
        if not inner:
            break
        e = inner
    return e

def _find_default_expr(tail: str) -> str | None:
    """
    Return the DEFAULT expression string with balanced parentheses.
    Examples:
      DEFAULT (newid())           -> "newid()"
      DEFAULT ((0))               -> "0"
      CONSTRAINT DF ... DEFAULT (getdate()) -> "getdate()"
    """
    if not tail:
        return None
    m = re.search(r"\bDEFAULT\b", tail, flags=re.I)
    if not m:
        return None
    i = m.end()
    n = len(tail)
    # skip whitespace
    while i < n and tail[i].isspace():
        i += 1
    # parenthesized form
    if i < n and tail[i] == "(":
        lvl = 0
        j = i
        while j < n:
            ch = tail[j]
            if ch == "(":
                lvl += 1
            elif ch == ")":
                lvl -= 1
                if lvl == 0:
                    expr = tail[i+1:j].strip()  # inside DEFAULT ( ... )
                    return _unwrap_parens(expr)
            j += 1
        # fallback (unbalanced) – trim whatever is left
        expr = tail[i:].strip()
        return _unwrap_parens(expr)
    # rare: DEFAULT <literal> (without parens)
    j = i
    while j < n and tail[j] not in (",", " ", "\t", "\r", "\n"):
        j += 1
    lit = tail[i:j].strip()
    return _unwrap_parens(lit) if lit else None
