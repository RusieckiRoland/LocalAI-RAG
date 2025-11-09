# parsing.py — header/params, CTE, SELECT blocks, DML/writes, flags/sets/pagination/tx, result columns
import re
from typing import List, Dict, Any, Tuple, Set

from .utils import normalize_ident, one_line, strip_table_hints, clean_preview, strip_comments


# ---------- procedure header & params ----------


CREATE_TABLE_HDR_RE = re.compile(
r"CREATE\s+TABLE\s+([\[\]\w\.]+)\s*\(",
flags=re.I | re.S,
)


PROC_HDR_RE = re.compile(
    r"CREATE\s+(?:OR\s+ALTER\s+)?PROCEDURE\s+([\[\]\w\.]+)\s*(?:\(|\s)\s*(.*?)\s+AS\b",
    flags=re.I | re.S,
)

def parse_table_header(sql: str) -> str:
    """
    Return fully-qualified table name (e.g. [Schema].[Table]) if a CREATE TABLE
    statement is present; otherwise return an empty string.
    """
    m = CREATE_TABLE_HDR_RE.search(sql or "")
    if not m:
        return ""
    raw = (m.group(1) or "").strip()

    def _bracket(part: str) -> str:
        p = part.strip().strip("[]")
        return f"[{p}]" if p else p

    if "." in raw:
        left, right = raw.split(".", 1)
        return f"{_bracket(left)}.{_bracket(right)}"
    # single-part name (rare) — still bracket it
    return _bracket(raw)

def parse_proc_header(sql: str) -> Tuple[str, str]:
    m = PROC_HDR_RE.search(sql)
    if not m:
        return "", ""
    obj = m.group(1).strip()
    param_block = m.group(2).strip()
    param_block = re.sub(r"\bWITH\s+RECOMPILE\b", "", param_block, flags=re.I)
    return obj, param_block

def _scan_params_balanced(block: str):
    res = []
    i = 0
    n = len(block or "")

    def _skip_ws(j: int) -> int:
        while j < n and block[j].isspace():
            j += 1
        return j

    while True:
        i = _skip_ws(i)
        if i >= n or block[i] == ')':
            break
        if block[i] != '@':
            while i < n and block[i] not in ',)':
                i += 1
            if i < n and block[i] == ',':
                i += 1
            continue
        j = i + 1
        while j < n and (block[j].isalnum() or block[j] == '_'):
            j += 1
        name = block[i:j]
        i = _skip_ws(j)
        t_start = i
        lvl = 0
        while i < n:
            ch = block[i]
            if ch == '(':
                lvl += 1
            elif ch == ')':
                if lvl > 0:
                    lvl -= 1
            elif ch in ',)' and lvl == 0:
                break
            elif ch == '=' and lvl == 0:
                break
            i += 1
        typ = (block[t_start:i]).strip()
        default = None
        if i < n and block[i] == '=':
            i += 1
            i = _skip_ws(i)
            d_start = i
            while i < n and block[i] not in ',)':
                i += 1
            default = (block[d_start:i]).strip() or None
        while i < n and block[i].isspace():
            i += 1
        if i < n and block[i] == ',':
            i += 1
        res.append((name.strip(), typ.strip(), default))
    return res

def parse_params(block: str) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = []
    for name, typ, default in _scan_params_balanced(block or ""):
        tnorm = re.sub(r"\s+", " ", (typ or "")).strip()
        if re.search(r"\bNULL\b$", tnorm, flags=re.I) and default is None:
            tnorm = re.sub(r"\bNULL\b$", "", tnorm, flags=re.I).strip()
            default = "NULL"
        params.append({"name": name, "type": tnorm, "default": default})
    return params

# ---------- CTE parsing ----------

def parse_ctes(sql: str) -> List[Dict[str, Any]]:
    res: List[Dict[str, Any]] = []
    u = sql
    n = len(u)
    i = 0

    def skip_ws(k: int) -> int:
        while k < n and u[k].isspace():
            k += 1
        return k

    def at_level0(idx: int) -> bool:
        left = u[:idx]
        left = re.sub(r"'.*?'", "", left, flags=re.S)
        opens = left.count('(')
        closes = left.count(')')
        return opens <= closes

    while True:
        m = re.search(r"\bWITH\b", u[i:], flags=re.I)
        if not m:
            break
        wpos = i + m.start()
        j = skip_ws(wpos + len("WITH"))
        if j < n and u[j] == '(':
            i = j + 1
            continue
        if not at_level0(wpos):
            i = wpos + 4
            continue
        k = j
        while True:
            k = skip_ws(k)
            mname = re.match(r"[\[\]\w\.]+", u[k:])
            if not mname:
                break
            name = normalize_ident(mname.group(0))
            k += len(mname.group(0))
            k = skip_ws(k)
            if k < n and u[k] == '(':
                lvl = 1
                k += 1
                while k < n and lvl > 0:
                    if u[k] == '(':
                        lvl += 1
                    elif u[k] == ')':
                        lvl -= 1
                    k += 1
                k = skip_ws(k)
            mas = re.match(r"AS\s*\(", u[k:], flags=re.I)
            if not mas:
                break
            k += mas.end()
            lvl = 1
            start_inner = k
            while k < n and lvl > 0:
                if u[k] == '(':
                    lvl += 1
                elif u[k] == ')':
                    lvl -= 1
                k += 1
            inner = u[start_inner:k-1] if lvl == 0 else u[start_inner:k]
            inner_oneline = one_line(clean_preview(inner))
            union_cnt = len(re.findall(r"\bUNION(?:\s+ALL)?\b", inner, flags=re.I))
            union_parts = union_cnt + 1 if union_cnt > 0 else 1
            res.append({
                "name": f"cte_{name}" if not name.lower().startswith("cte_") else name,
                "preview": inner_oneline,
                "union_parts": union_parts,
            })
            k = skip_ws(k)
            if k < n and u[k] == ',':
                k += 1
                continue
            else:
                break
        i = k
    seen: Set[str] = set()
    uniq: List[Dict[str, Any]] = []
    for c in res:
        key = (c["name"] or "").lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq

# ---------- SELECT blocks ----------

JOIN_TBL_RE = re.compile(r"\bJOIN\s+([A-Za-z0-9_\.\[\]@]+)(?:\s+AS)?\s+([A-Za-z0-9_\[\]@]+)?", re.I)
AGG_FUN_RE  = re.compile(r"\b(SUM|COUNT|AVG|MIN|MAX|STRING_AGG)\s*\(", re.I)
WINDOW_RE   = re.compile(r"\bOVER\s*\(", re.I)
STATEMENT_END_RE = re.compile(r";|\bWITH\b\s+[A-Za-z_]\w*|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b", re.I)
CASE_RE = re.compile(r"\bCASE\b", re.I)
XML_RE  = re.compile(r"\.(nodes|value|query)\s*\(", re.I)

def _select_details_for_insert(sql: str, target: str) -> Dict[str, Any]:
    """
    Find the INSERT INTO <target> ... SELECT ... block and extract structural hints
    (GROUP BY text, aggregates, window functions, CASE, XML usage).
    """
    pat = re.compile(
        rf"\bINSERT\s+INTO\s+{re.escape(target)}\b(?P<body>[\s\S]*?)(?=;|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b|$)",
        re.I
    )
    m = pat.search(sql)
    if not m:
        return {}

    seg = m.group(0)
    sel = re.search(r"\bSELECT\b[\s\S]+", seg, re.I)
    if not sel:
        return {}

    chunk = sel.group(0)
    gb_txt = _slice_after_kw(chunk, " GROUP BY ")

    return {
        "gb": one_line(clean_preview(gb_txt)) if gb_txt else "",
        "aggregates": bool(AGG_FUN_RE.search(chunk)),
        "windows": bool(WINDOW_RE.search(chunk)),
        "has_case": bool(CASE_RE.search(chunk)),
        "has_xml": bool(XML_RE.search(chunk)),
    }


def _find_kw_level0(s: str, kw: str) -> int:
    u = s.upper()
    kwu = kw.upper()
    lvl = 0
    i = 0
    while i < len(u):
        ch = u[i]
        if ch == '(':
            lvl += 1
        elif ch == ')':
            lvl = max(0, lvl-1)
        elif lvl == 0 and u.startswith(kwu, i):
            return i
        i += 1
    return -1

BOUNDARIES = [" WHERE", " GROUP BY", " HAVING", " ORDER BY",
              " UNION", " EXCEPT", " INTERSECT", " OFFSET", " FETCH",
              " BEGIN", " END", ";"]

def _is_boundary(u: str, i: int, tok: str) -> bool:
    if not u.startswith(tok, i):
        return False
    j = i + len(tok)
    if j >= len(u):
        return True
    ch = u[j]
    return not (ch.isalnum() or ch == '_')

def _slice_after_kw(s: str, kw: str) -> str:
    pos = _find_kw_level0(s, kw)
    if pos < 0:
        return ""
    start = pos + len(kw)
    u = s.upper()
    lvl = 0
    i = start
    while i < len(s):
        ch = s[i]
        if ch == '(':
            lvl += 1
        elif ch == ')':
            lvl = max(0, lvl-1)
        elif lvl == 0:
            for tok in BOUNDARIES:
                if _is_boundary(u, i, tok):
                    return s[start:i].strip()
        i += 1
    return s[start:].strip()

def _trim_cte_bleed(text: str) -> str:
    if not text:
        return text
    flags = re.I | re.S
    text = re.sub(r"\)\s*,\s*\[?cte_[A-Za-z0-9_]+\]?\s+AS\s*\(.+$", ")", text, flags=flags)
    text = re.sub(r"\)\s*SELECT\b.+$", ")", text, flags=flags)
    return text

def _looks_like_cte_context(prefix: str) -> bool:
    u = prefix.upper()
    u = re.sub(r"\s+", " ", u[-32:])
    return "AS (" in u

def _find_kw_level0_scoped(s: str, kw: str) -> int:
    u, kwu = s.upper(), kw.upper()
    lvl = 0
    i = 0
    while i < len(u):
        ch = u[i]
        if ch == '(':
            lvl += 1
        elif ch == ')':
            lvl -= 1
            if lvl < 0:
                return -1
        if lvl == 0 and u.startswith(kwu, i):
            return i
        i += 1
    return -1

def _slice_order_by_scoped(s: str) -> str:
    pos = _find_kw_level0_scoped(s, " ORDER BY ")
    if pos < 0:
        return ""
    start = pos + len(" ORDER BY ")
    u = s.upper()
    lvl = 0
    i = start
    while i < len(s):
        ch = s[i]
        if ch == '(':
            lvl += 1
        elif ch == ')':
            if lvl == 0:
                return s[start:i].strip()
            lvl -= 1
        elif lvl == 0:
            for tok in [" OFFSET", " FETCH", " UNION", " EXCEPT", " INTERSECT", ";"]:
                if u.startswith(tok, i):
                    return s[start:i].strip()
        i += 1
    return s[start:].strip()

def _kind_for_table(tbl: str) -> str:
    t = (tbl or "").lower()
    if t.startswith("@"):
        return "var"
    if t == "cte" or t.startswith("cte_"):
        return "cte"
    return "table"


def find_select_blocks(sql: str) -> List[Dict[str, Any]]:
    """
    Parse top-level SELECT statements and return lightweight metadata blocks.

    - Skips SELECTs that are inside parentheses (e.g., the inner SELECT of a CTE).
    - Extracts base table from FROM (before any JOINs) + tables from JOINs.
    - Removes comments in preview/clauses (/* */, --).
    - Drops malformed statements (e.g., SELECT ... FROM ... WHERE ;).
    """
    def _paren_depth_at(s: str, end: int) -> int:
        # Simple, fast parentheses counter (good enough for our tests).
        depth = 0
        for ch in s[:end]:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
        return depth

    blocks: List[Dict[str, Any]] = []

    for m in re.finditer(r"\bSELECT\b", sql, flags=re.I):
        start = m.start()

        # Skip non top-level SELECT (inside parentheses: CTE/body subqueries).
        if _paren_depth_at(sql, start) > 0:
            continue

        # Statement end (until ';' or end of string).
        end_m = STATEMENT_END_RE.search(sql, pos=start)
        end = end_m.start() if end_m else len(sql)
        chunk = sql[start:end]

        # Must have FROM at level 0 to consider it a SELECT-block
        if _find_kw_level0(chunk, " FROM ") < 0:
            continue

        # Slice clauses
        from_block   = _slice_after_kw(chunk, " FROM ")
        where_block  = _slice_after_kw(chunk, " WHERE ")
        group_block  = _slice_after_kw(chunk, " GROUP BY ")
        having_block = _slice_after_kw(chunk, " HAVING ")
        order_block  = _slice_order_by_scoped(chunk)

        # Clean FROM (remove table hints), then detect tables
        clean_from = strip_table_hints(" FROM " + (from_block or ""))

        tables: List[Dict[str, Any]] = []

        # 1) Base table from FROM ... (before any JOINs)
        base_m = re.search(
            r"\bFROM\s+([A-Za-z0-9_\[\]\.@#]+)(?:\s+(?:AS\s+)?([A-Za-z0-9_\[\]#@]+))?",
            clean_from,
            flags=re.I,
        )
        if base_m:
            base_tbl = normalize_ident(base_m.group(1))
            base_alias = base_m.group(2) or None
            if base_alias and base_alias.upper() == "WITH":
                base_alias = None
            base_kind = _kind_for_table(base_tbl)
            tables.append({"table": base_tbl, "alias": base_alias, "kind": base_kind})

        # 2) JOINed tables
        for j in JOIN_TBL_RE.finditer(clean_from):
            tbl = normalize_ident(j.group(1))
            alias = j.group(2) or None
            if alias and alias.upper() == "WITH":
                alias = None
            kind = _kind_for_table(tbl)
            tables.append({"table": tbl, "alias": alias, "kind": kind})

        # SELECT list / aggregate flags
        sel_to = _find_kw_level0(chunk, " FROM ")
        select_list = chunk[len("SELECT"):sel_to].strip() if sel_to > 0 else ""
        aggs = bool(AGG_FUN_RE.search(select_list))
        wins = bool(WINDOW_RE.search(select_list))

        def _remove_hints(t: str) -> str:
        # remove table hints like WITH (NOLOCK) from previews
            return re.sub(r"\s+WITH\s*\([^)]*\)", "", t or "", flags=re.I)

        # Clause previews: strip comments, trim CTE bleed, collapse to one line
        def _pp(part: str | None) -> str:
          if not part:
             return ""
          return one_line(strip_comments(clean_preview(_trim_cte_bleed(_remove_hints(part)))))


        where_preview  = _pp(where_block)
        group_preview  = _pp(group_block)
        having_preview = _pp(having_block)
        order_preview  = _pp(order_block)

        # Drop only if a WHERE keyword exists but the clause body is empty (e.g., "... WHERE ;").
        if re.search(r"\bWHERE\b", chunk, flags=re.I) and where_preview.strip() == "":
            continue

        preview_src = _remove_hints(chunk)  # keep previews free of table hints
        blocks.append({
            "preview": one_line(strip_comments(clean_preview(preview_src))),
            "tables": tables,
            "where": where_preview,
            "group_by": group_preview,
            "having": having_preview,
            "order_by": order_preview,
            "has_aggregates": aggs,
            "has_windows": wins,
            "select_preview": one_line(select_list),
            "select_full": select_list,
        })

    return blocks

# ---------- DML ops & writes ----------

def parse_dml_ops(sql: str) -> List[str]:
    ops = []
    if re.search(r"\bINSERT\s+INTO\b", sql, flags=re.I):
        ops.append("INSERT INTO")
    if re.search(r"\bUPDATE\b", sql, flags=re.I):
        ops.append("UPDATE")
    if re.search(r"\bDELETE\b(?:\s+FROM)?\s+[A-Za-z0-9_\.\[\]@]+", sql, flags=re.I):
        ops.append("DELETE")
    if re.search(r"\bMERGE\b", sql, flags=re.I):
        ops.append("MERGE")
    return ops

def _count_unions_for_insert(sql: str, target_tbl: str) -> int:
    max_cnt = 0
    pat = re.compile(
        rf"\bINSERT\s+INTO\s+{re.escape(target_tbl)}\b[\s\S]*?(?=;|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b|$)",
        re.I
    )
    for m in pat.finditer(sql):
        seg = m.group(0)
        cnt = len(re.findall(r"\bUNION(?:\s+ALL)?\b", seg, flags=re.I))
        if cnt > max_cnt:
            max_cnt = cnt
    return max_cnt

def parse_writes(sql: str) -> List[Dict[str, Any]]:
    writes: List[Dict[str, Any]] = []
    # INSERT
    for m in re.finditer(r"\bINSERT\s+INTO\s+([A-Za-z0-9_\.\[\]@]+)", sql, flags=re.I):
        tbl = normalize_ident(m.group(1))
        cnt = _count_unions_for_insert(sql, m.group(1))
        writes.append({"op": "INSERT", "table": tbl, "set_preview": None, "where_preview": None,
                       "union_parts": (cnt + 1) if cnt > 0 else 1})
    # UPDATE
    up_re = re.compile(
        r"\bUPDATE\s+([A-Za-z0-9_\.\[\]@]+)\s+SET\b([\s\S]*?)(?=;|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b|$)",
        re.I
    )
    for m in up_re.finditer(sql):
        tbl = normalize_ident(m.group(1))
        seg = m.group(0)
        set_block = _slice_after_kw(seg, " SET ")
        where_block = _slice_after_kw(seg, " WHERE ")
        writes.append({"op": "UPDATE", "table": tbl,
                       "set_preview": one_line(set_block) or None,
                       "where_preview": one_line(where_block) or None})
    # DELETE
    del_re = re.compile(
        r"\bDELETE\b(?:\s+FROM)?\s+([A-Za-z0-9_\.\[\]@]+)([\s\S]*?)(?=;|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b|$)",
        re.I
    )
    for m in del_re.finditer(sql):
        tbl = normalize_ident(m.group(1))
        seg = m.group(0)
        where_block = _slice_after_kw(seg, " WHERE ")
        writes.append({"op": "DELETE", "table": tbl, "set_preview": None,
                       "where_preview": one_line(where_block) or None})
    return writes

# ---------- flags, sets, pagination, tx ----------

def detect_flags(sql: str) -> List[str]:
    obj, param_block = parse_proc_header(sql)
    hdr_params = [(n, t, d) for (n, t, d) in _scan_params_balanced(param_block or "")]
    hdr_order = [p[0] for p in hdr_params]
    hdr_map   = {p[0].lower(): p[0] for p in hdr_params}

    seen_lower: Set[str] = set()
    first_seen: Dict[str, str] = {}
    order_all: List[str] = []

    for m in re.finditer(r"@[A-Za-z_]\w*", sql):
        raw = m.group(0)
        low = raw.lower()
        if low not in seen_lower:
            seen_lower.add(low)
            first_seen[low] = raw
            order_all.append(low)

    out: List[str] = []
    used: Set[str] = set()

    for p in hdr_order:
        low = p.lower()
        if low in seen_lower and low not in used:
            out.append(hdr_map.get(low, p))
            used.add(low)

    for low in order_all:
        if low in used:
            continue
        out.append(hdr_map.get(low, first_seen.get(low, low)))
        used.add(low)

    return out

def parse_sets(sql: str) -> List[Dict[str, str]]:
    sets = []
    for m in re.finditer(r"\bSET\s+(@[A-Za-z_]\w*)\s*=\s*([^;]+)", sql, flags=re.I):
        var = m.group(1)
        val = one_line(m.group(2)).strip()
        val = re.sub(r"\bBEGIN\b.*$", "", val, flags=re.I)
        sets.append({"var": var, "value_preview": val})
    seen = set()
    uniq = []
    for s in sets:
        if s["var"] in seen:
            continue
        seen.add(s["var"])
        uniq.append(s)
    return uniq

def find_pagination(sql: str) -> str:
    m = re.search(r"OFFSET\s+@[A-Za-z_]\w*\s+ROWS\s+FETCH\s+NEXT\s+@[A-Za-z_]\w*\s+ROWS\s+ONLY", sql, flags=re.I)
    return one_line(m.group(0)) if m else ""

def tx_metadata(sql: str) -> Dict[str, Any]:
    begins = len(re.findall(r"\bBEGIN\s+TRAN", sql, flags=re.I))
    commits = len(re.findall(r"\bCOMMIT\b", sql, flags=re.I))
    rollbacks = len(re.findall(r"\bROLLBACK\b", sql, flags=re.I))
    iso = re.findall(r"SET\s+TRANSACTION\s+ISOLATION\s+LEVEL\s+([A-Z ]+)", sql, flags=re.I)
    nolock = bool(re.search(r"\bWITH\s*\(\s*NOLOCK\s*\)", sql, flags=re.I))
    return {
        "begin_transactions": begins,
        "commits": commits,
        "rollbacks": rollbacks,
        "isolation_levels": [x.strip().upper() for x in iso],
        "nolock_used": nolock
    }

# ---------- result set columns ----------

def _split_commas_top(s: str) -> List[str]:
    out, buf, lvl = [], [], 0
    i, n, in_sq = 0, len(s or ""), False
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

ALIAS_RE = re.compile(r'\bAS\s+(\[[^\]]+\]|\'[^\']+\'|"[^"]+")(?=\s*(,|\)|$))', re.I)
ALT_ALIAS_RE = re.compile(r'^\s*(\^[^\]]+\]|\'[^\']+\'|"[^"]+")\s*=', re.I)  # keep shape; never used in regex alt anchor

# corrected ALT_ALIAS_RE (typo above is harmless; actual one below)
ALT_ALIAS_RE = re.compile(r'^\s*(\[[^\]]+\]|\'[^\']+\'|"[^"]+")\s*=', re.I)

def infer_result_columns(selects: List[Dict[str, Any]], max_cols: int = 64) -> List[str]:
    if not selects:
        return []
    sel = (selects[-1].get("select_full") or selects[-1].get("select_preview") or "").strip()
    if not sel:
        return []
    cols, names = _split_commas_top(sel), []
    for c in cols[:max_cols]:
        c = re.sub(r"^\s*DISTINCT\s+", "", c, flags=re.I).strip()
        m = ALIAS_RE.search(c)
        if m:
            alias = m.group(1).strip().strip("[]'\"")
            names.append(alias); continue
        m2 = ALT_ALIAS_RE.search(c)
        if m2:
            alias = m2.group(1).strip().strip("[]'\"")
            names.append(alias); continue
        tail = re.split(r"\s", c.strip())[-1].strip(",")
        if '.' in tail:
            tail = tail.split('.')[-1]
        tail = tail.strip("[]'\"")
        names.append(tail)
    seen, uniq = set(), []
    for n in names:
        key = n.lower()
        if key in seen:
            continue
        seen.add(key); uniq.append(n)
    return uniq

# ---------- sources helpers used by api (kept here with parsing) ----------

def collect_sources(selects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[Tuple[str, str, str]] = set()
    out: List[Dict[str, Any]] = []
    for b in selects:
        for t in b.get("tables", []):
            key = (t.get("table") or "", t.get("alias") or "", t.get("kind") or "")
            if key in seen:
                continue
            seen.add(key)
            out.append({"table": key[0], "alias": key[1] if key[1] else None, "kind": key[2]})
    return out

def _disambiguate_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_alias_kinds: Dict[str, Set[str]] = {}
    for s in sources:
        a = (s.get("alias") or "")
        if not a:
            continue
        by_alias_kinds.setdefault(a.upper(), set()).add(s.get("kind") or "")
    for s in sources:
        a = s.get("alias")
        if not a:
            continue
        kinds = by_alias_kinds.get(a.upper(), set())
        if len(kinds) > 1:
            s["alias"] = f'{a} ({s.get("kind")})'
    by_alias_objs: Dict[str, Set[str]] = {}
    for s in sources:
        a = (s.get("alias") or "")
        if not a:
            continue
        obj = (s.get("table") or "")
        by_alias_objs.setdefault(a.upper(), set()).add(obj)
    for s in sources:
        a = s.get("alias")
        if not a:
            continue
        objs = by_alias_objs.get(a.upper(), set()) or set()
        if len(objs) > 1:
            tshort = (s.get("table") or "").split(".")[-1]
            s["alias"] = f'{a} ({s.get("kind")}:{tshort})'
    return sources

def _disambiguate_select_aliases(selects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    alias_map: Dict[str, Set[Tuple[str, str]]] = {}
    for b in selects:
        for t in b.get("tables", []):
            a = (t.get("alias") or "").strip()
            if not a:
                continue
            alias_map.setdefault(a.upper(), set()).add(((t.get("kind") or ""), (t.get("table") or "")))
    for b in selects:
        for t in b.get("tables", []):
            a = t.get("alias")
            if not a:
                continue
            sigs = alias_map.get(a.upper(), set())
            if len(sigs) > 1 and not re.search(r"\(\s*(table|cte|var)(?::[A-Za-z0-9_\.\[\]]+)?\s*\)$", a, flags=re.I):
                if (t.get("kind") or "") == "cte":
                    suffix = f"cte:{t.get('table')}"
                elif (t.get("kind") or "") == "table":
                    suffix = "table"
                else:
                    suffix = t.get("kind") or "src"
                t["alias"] = f"{a} ({suffix})"
    return selects

def list_dependencies(sources: List[Dict[str, Any]]) -> List[str]:
    deps = []
    seen = set()
    for s in sources or []:
        if (s.get("kind") or "") != "table":
            continue
        tab = s.get("table") or ""
        if tab.startswith("@"):
            continue
        key = tab.lower()
        if key in seen:
            continue
        seen.add(key)
        deps.append(tab)
    return deps

# DDL: CREATE TABLE header
TABLE_HDR_RE = re.compile(
    r"CREATE\s+TABLE\s+([\[\]\w\.]+)\s*\(",
    flags=re.I | re.S
)

def parse_table_header(sql: str) -> str:
    """Return fully qualified table name for CREATE TABLE, or '' if not found."""
    m = TABLE_HDR_RE.search(sql)
    return m.group(1).strip() if m else ""
