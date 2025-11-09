# analysis.py — filters, robust IF/flow_tree, deps augment (RAG-first, generic)
import re
from typing import List, Dict, Any, Tuple

from .parsing import AGG_FUN_RE, WINDOW_RE, _count_unions_for_insert, _select_details_for_insert
from .utils import one_line, clean_preview

# =====================================================
# Pomocnicze: normalizacja do [Schema].[Object]
# =====================================================
def _normalize_ident_bracketed(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", "", str(text))
    if t.startswith("@") or t.startswith("#"):
        return t
    if "." not in t:
        return t
    schema, obj = t.split(".", 1)
    schema = schema.strip("[]")
    obj = obj.strip("[]")
    return f"[{schema}].[{obj}]"

# =====================================================
# Usuwanie komentarzy i wykrywanie FINAL SELECT
# =====================================================

_SL_COMMENT = re.compile(r"--[^\n]*")
_ML_COMMENT = re.compile(r"/\*[\s\S]*?\*/")

def _strip_sql_comments(sql: str) -> str:
    if not sql:
        return ""
    s = _ML_COMMENT.sub("", sql)
    s = _SL_COMMENT.sub("", s)
    return s

STATEMENT_HEAD_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|EXEC|TRUNCATE|RETURN|COMMIT|ROLLBACK|BEGIN|END|SET)\b",
    re.I,
)

def _is_assignment_select_tail(tail: str) -> bool:
    # SELECT @var = ...
    return bool(re.match(r"\s+@[A-Za-z_]\w*\s*=", tail, flags=re.I))

def _is_select_into_tail(tail: str) -> bool:
    # SELECT ... INTO ...
    return bool(re.match(r"\s+(TOP\s+\d+\s+)?(?:\*|[\s\S]+?)\bINTO\b", tail, flags=re.I))

def _looks_like_resultset_select_tail(tail: str) -> bool:
    # Ma FROM/UNION/JOIN lub listę kolumn/gwiazdka (heurystycznie)
    w = tail[:400].upper()
    if (" FROM " in w) or (" UNION " in w) or (" JOIN " in w):
        return True
    return bool(re.match(r"\s+(TOP\s+\d+\s+)?(\*|[A-Za-z0-9_\[\]\"']+(\s*,\s*[A-Za-z0-9_\[\]\"']+)*)", tail, flags=re.I))

def _has_final_result_select(sql: str) -> bool:
    """
    True tylko jeśli OSTATNIA znacząca instrukcja w tekście to wynikowy SELECT,
    a nie: SELECT INTO, SELECT @var = ..., ani SET @var = (SELECT ...).

    Heurystyka:
      1) Wycina komentarze.
      2) Znajduje ostatnie "głowy" instrukcji (SELECT/UPDATE/...).
      3) Jeśli ostatnia głowa to SELECT → sprawdza tail:
         - nie może być SELECT INTO
         - nie może być SELECT @var = ...
         - tail musi wyglądać jak wynikowy SELECT
      4) Dodatkowy filtr: nie jest to wzorzec SET @x = (SELECT ...).
    """
    if not sql:
        return False
    s = _strip_sql_comments(sql)
    s_flat = re.sub(r"\s+", " ", s).strip()

    # quick guard: jeśli nie ma SELECTa, to nie ma finału
    if "SELECT" not in s_flat.upper():
        return False

    # znajdź wszystkie "głowy" instrukcji i wybierz ostatnią
    heads = list(STATEMENT_HEAD_RE.finditer(s_flat))
    if not heads:
        return False

    last = heads[-1]
    last_kw = last.group(1).upper()
    last_tail = s_flat[last.end():]

    # Jeżeli ostatnią głową nie jest SELECT → brak final SELECT
    if last_kw != "SELECT":
        return False

    # Odrzuć SELECT INTO i SELECT @var =
    if _is_select_into_tail(last_tail):
        return False
    if _is_assignment_select_tail(last_tail):
        return False

    # Odrzuć wzorzec SET @x = (SELECT ...) blisko końca
    # (szukamy SET @... = (SELECT ...) w ostatnim fragmencie tekstu)
    window_start = max(0, last.start() - 120)
    near_prefix = s_flat[window_start:last.start()]
    if re.search(r"SET\s+@[A-Za-z_]\w*\s*=\s*\(\s*$", near_prefix, flags=re.I):
        return False

    # Sprawdź czy tail wygląda jak wynikowy SELECT (FROM/UNION/JOIN lub lista kolumn)
    if not _looks_like_resultset_select_tail(last_tail):
        return False

    # Dodatkowe zabezpieczenie: ostatni SELECT powinien być naprawdę na końcu (ostatnie ~25%)
    if last.start() < int(len(s_flat) * 0.75):
        return False

    # Po SELECT mogą wystąpić tylko białe znaki, ewentualnie ) ; END RETURN COMMIT itp.
    tail_after = last_tail.upper()
    # jeśli po SELECT pojawiają się kolejne "głowy" typu UPDATE/INSERT itd. → to nie jest final
    if re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|EXEC|TRUNCATE)\b", tail_after, flags=re.I):
        return False

    return True

# =====================================================
# WHERE / FILTERS — kanonizacja i deduplikacja
# =====================================================

WHERE_PRED_RE = re.compile(r"""
    (?P<lhs>[A-Za-z0-9_\.\[\]]+)\s+
    (?P<op>=|<>|!=|>=|<=|>|<|\bIN\b|\bNOT\s+IN\b)
    \s*
    (?P<rhs>
        \([^)]+\)
      | N?'(?:''|[^'])*'
      | DATEADD\s*\((?:[^()]*|\([^()]*\))*\)
      | CURRENT_TIMESTAMP|GETDATE\(\)
      | [A-Za-z0-9_\.\[\]@]+
    )
""", re.I | re.X)

SIMPLE_EQ_STR_RE = re.compile(r"([A-Za-z0-9_\.\[\]]+)\s*=\s*(N?'(?:''|[^']*)')", re.I)
SIMPLE_NOTIN_RE  = re.compile(r"([A-Za-z0-9_\.\[\]]+)\s+NOT\s+IN\s*\(([^)]*)\)", re.I)

_EQ_KEY_RE   = re.compile(r"^(?:(?P<alias>[A-Za-z_]\w+)\.)?(?P<col>[A-Za-z_]\w+)\s*=\s*(?P<rhs>.+)$", re.I)
_COMP_KEY_RE = re.compile(r"^(?:(?P<alias>[A-Za-z_]\w+)\.)?(?P<col>[A-Za-z_]\w+)\s*(?P<op>>=|<=|!=|=|>|<)\s*(?P<rhs>.+)$", re.I)

def _normalize_nprefix_literals(s: str) -> str:
    return re.sub(r"\bN'([^']*)'", r"'\1'", s)

def _lhs_norm(lhs: str) -> str:
    return re.sub(r"\s+", " ", (lhs or "")).strip()

def _canon_sig(s: str) -> str:
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"!\s*=", "!=", s)
    s = re.sub(r">\s*=", ">=", s)
    s = re.sub(r"<\s*=", "<=", s)
    s = re.sub(r"\s*(>=|<=|!=|=|>|<)\s*", r" \1 ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s

def _eq_key(sig: str):
    m = _EQ_KEY_RE.match(sig)
    if not m:
        return None
    col = (m.group("col") or "").lower()
    rhs = re.sub(r"\s+", " ", (m.group("rhs") or "")).lower()
    return (col, rhs)

def _comp_key(sig: str):
    m = _COMP_KEY_RE.match(sig)
    if not m:
        return None
    col = (m.group("col") or "").lower()
    op  = (m.group("op") or "").upper()
    rhs = re.sub(r"\s+", " ", (m.group("rhs") or "")).lower()
    return (col, op, rhs)

def _has_alias(sig: str, regex) -> bool:
    m = regex.match(sig)
    return bool(m and m.group("alias"))

def _dedup_list(values: List[str]) -> List[str]:
    out, seen = [], set()
    for v in values or []:
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out

def _prefer_qualified(values: List[str], key_fn, regex) -> List[str]:
    items = [_canon_sig(v) for v in (values or [])]
    best: Dict[Any, str] = {}
    order_keys: List[Any] = []
    for s in items:
        key = key_fn(s)
        if key is None:
            rawkey = ("__raw__", s.lower())
            if rawkey not in best:
                best[rawkey] = s
                order_keys.append(rawkey)
            continue
        if key not in best:
            best[key] = s
            order_keys.append(key)
        else:
            cur = best[key]
            if not _has_alias(cur, regex) and _has_alias(s, regex):
                best[key] = s
    out = []
    seen = set()
    for k in order_keys:
        s = best[k]
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def _dedup_equals_prefer_qualified(values: List[str]) -> List[str]:
    return _prefer_qualified(values, _eq_key, _EQ_KEY_RE)[:24]

def _dedup_comparisons_prefer_qualified(values: List[str]) -> List[str]:
    return _prefer_qualified(values, _comp_key, _COMP_KEY_RE)[:24]

def _normalize_pred(lhs: str, op: str, rhs: str) -> str:
    lhs = _lhs_norm(lhs)
    opu = re.sub(r"\s+", " ", (op or "")).upper().strip()
    rhs = (rhs or "").strip()
    if opu in ("IN", "NOT IN"):
        if not (rhs.startswith("(") and rhs.endswith(")")):
            rhs = "(" + re.sub(r"\s+", " ", rhs.strip("() ")) + ")"
        inner = re.sub(r"\s*,\s*", ", ", rhs.strip("() "))
        rhs = f"({inner})"
    rhs = _normalize_nprefix_literals(rhs)
    return _canon_sig(f"{lhs} {opu if opu != '=' else '='} {rhs}")

def _postprocess_filters(d: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for bucket, arr in (d or {}).items():
        if not arr:
            continue
        if bucket == "equals":
            arr2 = _dedup_equals_prefer_qualified(arr)
        elif bucket == "comparisons":
            arr2 = _dedup_comparisons_prefer_qualified(arr)
        else:
            arr2 = _dedup_list([_canon_sig(x) for x in arr])
        if arr2:
            out[bucket] = arr2[:24]
    return out

def summarize_filters(selects: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    raw = {"equals": [], "in": [], "not_in": [], "comparisons": [], "like_exists": []}

    def _add(bucket: str, sig: str):
        raw.setdefault(bucket, []).append(sig)

    for s in selects or []:
        w = (s.get("where") or "").strip()
        if not w:
            continue

        for m in WHERE_PRED_RE.finditer(w):
            sig = _normalize_pred(m.group("lhs"), m.group("op"), m.group("rhs"))
            opu = re.sub(r"\s+", " ", (m.group("op") or "").upper()).strip()
            if opu == "IN":
                _add("in", sig)
            elif opu == "NOT IN":
                _add("not_in", sig)
            elif opu == "=":
                _add("equals", sig)
            else:
                _add("comparisons", sig)

        for m in SIMPLE_EQ_STR_RE.finditer(w):
            lhs, rhs = m.group(1), m.group(2)
            _add("equals", _normalize_pred(lhs, "=", rhs))

        for m in SIMPLE_NOTIN_RE.finditer(w):
            lhs = re.sub(r"\s+", " ", (m.group(1) or "")).strip()
            items = ", ".join([x.strip() for x in m.group(2).split(",") if x.strip()])
            if items:
                _add("not_in", _canon_sig(f"{lhs} NOT IN ({items})"))

        if re.search(r"\bLIKE\b", w, flags=re.I): _add("like_exists", "LIKE …")
        if re.search(r"\bEXISTS\s*\(", w, flags=re.I): _add("like_exists", "EXISTS(…)")

    for k in list(raw.keys()):
        if not raw[k]:
            del raw[k]
    return _postprocess_filters(raw)

WHERE_BLOCK_RE = re.compile(
    r"\bWHERE\b\s+(?P<body>[\s\S]*?)(?=;|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bMERGE\b|\bWITH\b|\bSELECT\b|$)",
    re.I
)

def summarize_filters_global(sql: str, selects: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    merged = summarize_filters(selects)
    buckets = {
        "equals": list(merged.get("equals", [])),
        "in": list(merged.get("in", [])),
        "not_in": list(merged.get("not_in", [])),
        "comparisons": list(merged.get("comparisons", [])),
        "like_exists": list(merged.get("like_exists", [])),
    }

    for wm in WHERE_BLOCK_RE.finditer(sql or ""):
        w_raw = wm.group("body") or ""
        faux = [{"where": w_raw}]
        extra = summarize_filters(faux)
        for k, vals in (extra or {}).items():
            if not vals:
                continue
            buckets.setdefault(k, []).extend(vals)

    return _postprocess_filters(buckets)

# =====================================================
# Dependencies (TVF w FROM/JOIN)
# =====================================================

FUNC_IN_FROM_RE = re.compile(
    r"(?:FROM|JOIN)\s+((?:\[[^\]]+\]|[A-Za-z_]\w*)\.(?:\[[^\]]+\]|[A-Za-z_]\w*))\s*\(",
    re.I
)

def augment_dependencies(sql: str, deps: List[str]) -> List[str]:
    have = {d.lower() for d in deps}
    for m in FUNC_IN_FROM_RE.finditer(sql or ""):
        obj = _normalize_ident_bracketed(m.group(1))
        if obj.lower() not in have:
            deps.append(obj); have.add(obj.lower())
    return deps

# =====================================================
# FLOW: robust IF parsing + DML + DECL + Final (warunkowo)
# =====================================================

IF_HEADER_RE = re.compile(
    r"""
    \bIF\s*
    \(\s*(?P<cond>[\s\S]*?)\)\s*
    (?=(BEGIN|SET|UPDATE|INSERT|DELETE|SELECT|RETURN|ELSE|;))
    """,
    re.I | re.X
)

BEGIN_BLOCK_RE = re.compile(r"\bBEGIN\b\s*(?P<body>[\s\S]*?)\s*\bEND\b", re.I)
SINGLE_STMT_RE = re.compile(r"^(?!BEGIN\b)(?P<stmt>[\s\S]*?)(?=(?:\bELSE\b|$))", re.I)
ELSE_RE = re.compile(r"\bELSE\b\s*", re.I)

ACTION_PATTS = [
    ("INSERT", re.compile(r"\bINSERT\s+INTO\s+([A-Za-z0-9_\.\[\]@]+)", re.I)),
    ("UPDATE", re.compile(r"\bUPDATE\s+([A-Za-z0-9_\.\[\]@]+)\s+SET\b", re.I)),
    ("DELETE", re.compile(r"\bDELETE\b(?:\s+FROM)?\s+([A-Za-z0-9_\.\[\]@]+)", re.I)),
    ("SET",    re.compile(r"\bSET\s+(@[A-Za-z_]\w*)\s*=", re.I)),
    ("RETURN", re.compile(r"\bRETURN\b", re.I)),
    ("SELECT", re.compile(r"\bSELECT\b", re.I)),
]

def _list_actions(snippet: str) -> List[Dict[str, str]]:
    hits = []
    for kind, rx in ACTION_PATTS:
        for m in rx.finditer(snippet or ""):
            hits.append((m.start(), kind, m))
    hits.sort(key=lambda x: x[0])
    out = []
    for _, kind, m in hits:
        if kind == "INSERT":
            out.append({"step": f"INSERT INTO {_normalize_ident_bracketed(m.group(1))}"})
        elif kind == "UPDATE":
            out.append({"step": f"UPDATE {_normalize_ident_bracketed(m.group(1))}"})
        elif kind == "DELETE":
            out.append({"step": f"DELETE {_normalize_ident_bracketed(m.group(1))}"})
        elif kind == "SET":
            out.append({"step": f"SET {m.group(1)} = …"})
        elif kind == "RETURN":
            out.append({"step": "RETURN"})
        else:
            out.append({"step": "SELECT"})
    dedup = []
    for a in out:
        if dedup and dedup[-1] == a:
            continue
        dedup.append(a)
    return dedup[:12]

def _parse_if_blocks(sql: str) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    pos = 0
    text = sql or ""
    while True:
        m = IF_HEADER_RE.search(text, pos)
        if not m:
            break

        cond = one_line(clean_preview(m.group("cond") or ""))
        node = {"if": cond, "then": [], "else": []}

        after = text[m.end():]
        bm = BEGIN_BLOCK_RE.match(after)
        if bm:
            body = bm.group("body") or ""
            node["then"] = _list_actions(body)
            tail_start = m.end() + bm.end()
        else:
            sm = SINGLE_STMT_RE.match(after)
            stmt = (sm.group("stmt") if sm else "") or ""
            node["then"] = _list_actions(stmt)
            tail_start = m.end() + (sm.end() if sm else 0)

        em = ELSE_RE.match(text, tail_start)
        if em:
            after_else = text[em.end():]
            bm2 = BEGIN_BLOCK_RE.match(after_else)
            if bm2:
                body2 = bm2.group("body") or ""
                node["else"] = _list_actions(body2)
                pos = em.end() + bm2.end()
            else:
                sm2 = SINGLE_STMT_RE.match(after_else)
                stmt2 = (sm2.group("stmt") if sm2 else "") or ""
                node["else"] = _list_actions(stmt2)
                pos = em.end() + (sm2.end() if sm2 else 0)
        else:
            pos = tail_start

        nodes.append(node)

    return nodes

DECL_CONST_RE = re.compile(
    r"\bDECLARE\s+@([A-Za-z_]\w*)\s*(?:AS\s+)?[A-Za-z]+(?:\s*\(\s*\d+\s*\))?\s*=\s*('(?:''|[^'])*'|\d+)",
    re.I
)

def _insert_targets_en(sql: str) -> List[str]:
    steps = []
    seen = set()
    for m in re.finditer(r"\bINSERT\s+INTO\s+([A-Za-z0-9_\.\[\]@]+)", sql, flags=re.I):
        tbl = _normalize_ident_bracketed(m.group(1))
        if ("INS", tbl) in seen:
            continue
        seen.add(("INS", tbl))
        union_ct = _count_unions_for_insert(sql, tbl)
        steps.append(f"INSERT INTO {tbl}" + (f" (UNION x{union_ct})" if union_ct and union_ct > 1 else ""))
    for m in re.finditer(r"\bUPDATE\s+([A-Za-z0-9_\.\[\]@]+)\s+SET\b", sql, flags=re.I):
        tbl = _normalize_ident_bracketed(m.group(1))
        if ("UPD", tbl) in seen:
            continue
        seen.add(("UPD", tbl))
        steps.append(f"UPDATE {tbl}")
    for m in re.finditer(r"\bDELETE\b(?:\s+FROM)?\s+([A-Za-z0-9_\.\[\]@]+)", sql, flags=re.I):
        tbl = _normalize_ident_bracketed(m.group(1))
        if ("DEL", tbl) in seen:
            continue
        seen.add(("DEL", tbl))
        steps.append(f"DELETE {tbl}")
    return steps

def _collect_if_steps(nodes: List[Dict[str, Any]]) -> set:
    steps = set()
    for node in nodes or []:
        for branch in ("then", "else"):
            for act in (node.get(branch) or []):
                s = str(act.get("step") or "").strip()
                if s:
                    steps.add(s)
    return steps

def build_flow_en(sql: str, payload: Dict[str, Any]) -> List[str]:
    steps: List[str] = []

    if_nodes = _parse_if_blocks(sql)
    for node in if_nodes:
        act = node.get("then", [{}])[0].get("step", "…") if node.get("then") else "…"
        steps.append(f"IF {node.get('if','')} → {act}")

    decls = []
    for m in DECL_CONST_RE.finditer(sql or ""):
        name = m.group(1); val = m.group(2)
        decls.append(f"@{name}={val}")
    if decls:
        head = ", ".join(decls[:8]) + (" …" if len(decls) > 8 else "")
        steps.append("DECLARE constants: " + head)

    if_steps = _collect_if_steps(if_nodes)
    global_dml = []
    for t in _insert_targets_en(sql):
        if t.strip() in if_steps:
            continue
        if any(t.strip() == s.strip() for s in steps):
            continue
        global_dml.append(t)

    steps.extend(global_dml)

    # <-- warunkowo: tylko jeśli ostatnia instrukcja to wynikowy SELECT
    if _has_final_result_select(sql):
        steps.append("Final SELECT")
    return steps

def build_flow_tree(sql: str, flow_steps: List[str]) -> List[Dict[str, Any]]:
    tree: List[Dict[str, Any]] = []

    if_nodes = _parse_if_blocks(sql)
    tree.extend(if_nodes)

    decls = []
    for m in DECL_CONST_RE.finditer(sql or ""):
        name = m.group(1); val = m.group(2)
        decls.append(f"@{name}={val}")
    if decls:
        head = ", ".join(decls[:8]) + (" …" if len(decls) > 8 else "")
        tree.append({"step": "DECLARE constants: " + head})

    if_steps = _collect_if_steps(if_nodes)
    for t in _insert_targets_en(sql):
        if t.strip() in if_steps:
            continue
        tree.append({"step": t})

    # <-- warunkowo: tylko jeśli ostatnia instrukcja to wynikowy SELECT
    if _has_final_result_select(sql):
        tree.append({"step": "Final SELECT"})
    return tree

# =====================================================
# PURPOSE: automatyczne, GENERYCZNE wykrywanie celu
# =====================================================

VAR_EQ_RE = re.compile(
    r"^(?:(?P<alias>[A-Za-z_]\w+)\.)?(?P<col>[A-Za-z_]\w+)\s*=\s*(?P<rhs>@[A-Za-z_]\w+|'[^']*'|\d+|[A-Za-z0-9_\.\[\]]+)$",
    re.I
)
STATUS_IN_RE = re.compile(r"(?i)\bstatus\s+in\s*\(([^)]*)\)")
DATEADD_MIN_RE = re.compile(r"(?i)dateadd\s*\(\s*minute\s*,\s*-(\d+)\s*,\s*(getdate\s*\(\s*\)|current_timestamp)\s*\)")
DATEADD_HOUR_RE = re.compile(r"(?i)dateadd\s*\(\s*hour\s*,\s*-(\d+)\s*,\s*(getdate\s*\(\s*\)|current_timestamp)\s*\)")

def _collect_status_codes_from_set(set_text: str) -> List[str]:
    vals = []
    for m in re.finditer(r"\bStatus\s*=\s*'([^']+)'", set_text or "", flags=re.I):
        vals.append(m.group(1))
    out = []
    seen = set()
    for v in vals:
        if v not in seen:
            seen.add(v); out.append(v)
    return out

def _tables_by_op(writes: List[Dict[str, Any]]) -> Tuple[List[str], List[str], List[str]]:
    inserts, updates, deletes = [], [], []
    for w in writes or []:
        op = (w.get("op") or w.get("operation") or "").upper()
        tbl = _normalize_ident_bracketed(w.get("table") or "")
        if not tbl or tbl.startswith("@") or tbl.startswith("#"):
            continue
        if op == "INSERT":
            inserts.append(tbl)
        elif op == "UPDATE":
            updates.append(tbl)
        elif op == "DELETE":
            deletes.append(tbl)
    def uniq(xs):
        out, seen = [], set()
        for x in xs:
            if x.lower() in seen: continue
            seen.add(x.lower()); out.append(x)
        return out
    return uniq(inserts), uniq(updates), uniq(deletes)

def _first_n(xs: List[str], n: int) -> str:
    if not xs: return ""
    if len(xs) <= n: return ", ".join(xs)
    return ", ".join(xs[:n]) + ", …"

def infer_purpose(payload: Dict[str, Any]) -> str:
    obj = payload.get("object") or payload.get("obj") or ""
    filters = payload.get("filters") or {}
    writes = payload.get("writes_to") or payload.get("writes") or []

    inserts, updates, deletes = _tables_by_op(writes)

    status_codes = []
    for w in writes or []:
        setp = (w.get("set_preview") or w.get("set") or "") or ""
        status_codes.extend(_collect_status_codes_from_set(setp))
    scodes = []
    seen = set()
    for s in status_codes:
        if s not in seen:
            seen.add(s); scodes.append(s)

    log_tables = [t for t in inserts if re.search(r"(history|log)", t, flags=re.I)]
    main_inserts = [t for t in inserts if t not in log_tables]

    equals = [e for e in (filters.get("equals") or [])]
    in_list = [e for e in (filters.get("in") or [])]
    comparisons = [e for e in (filters.get("comparisons") or [])]

    file_like_cols = []
    VAR_EQ_RE_LOC = re.compile(
        r"^(?:(?P<alias>[A-Za-z_]\w+)\.)?(?P<col>[A-Za-z_]\w+)\s*=\s*(?P<rhs>@[A-Za-z_]\w+|'[^']*'|\d+|[A-Za-z0-9_\.\[\]]+)$",
        re.I
    )
    for e in equals:
        sig = _canon_sig(e)
        m = VAR_EQ_RE_LOC.match(sig)
        if not m:
            continue
        col = m.group("col") or ""
        if re.search(r"file(name)?", col, flags=re.I):
            file_like_cols.append(col)

    status_in_codes = []
    for e in in_list:
        m = re.search(r"(?i)\bstatus\s+in\s*\(([^)]*)\)", e)
        if m:
            inner = m.group(1)
            for s in re.findall(r"'([^']+)'", inner):
                if s not in status_in_codes:
                    status_in_codes.append(s)

    has_id_neq = any(re.search(r"(?i)\b[A-Za-z_]\w*Id\b\s*!=\s*@\w+", c) for c in comparisons)

    minutes = []
    for c in comparisons:
        for m in DATEADD_MIN_RE.finditer(c):
            try: minutes.append(int(m.group(1)))
            except: pass
        for m in DATEADD_HOUR_RE.finditer(c):
            try: minutes.append(int(m.group(1)) * 60)
            except: pass
    lease_txt = f"stosuje leasing czasowy ~{min(minutes)} min" if minutes else ""

    feats: List[str] = []

    if file_like_cols or re.search(r"file", obj, flags=re.I):
        col_hint = f" (wykryto kolumnę: {file_like_cols[0]})" if file_like_cols else ""
        feats.append("przetwarza plik(i) wejściowe" + col_hint)

    if main_inserts:
        feats.append(f"wstawia rekordy do {_first_n(main_inserts, 2)}")

    if log_tables:
        feats.append(f"loguje zdarzenia do {_first_n(log_tables, 2)}")

    if updates and scodes:
        feats.append(f"zarządza statusami ({', '.join(scodes[:6])}) w {_first_n(updates, 2)}")
    elif updates:
        feats.append(f"aktualizuje rekordy w {_first_n(updates, 2)}")

    if lease_txt:
        feats.append(lease_txt)

    if status_in_codes and has_id_neq:
        feats.append(f"eliminuje duplikaty wg kolumny FileName przy Status IN ({', '.join(status_in_codes)})")

    if not feats:
        feats.append("przetwarza dane i aktualizuje statusy rekordów")

    prefix = f"Procedura {obj}: "
    return prefix + "; ".join(feats)
