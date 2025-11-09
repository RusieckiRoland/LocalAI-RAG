# tsql_summarizer/emit.py — RAG-only emitter: neutralny purpose + czyste deps
import re
from typing import Dict, Any, List, Set

try:
    from .utils import one_line
except Exception:
    def one_line(s: str) -> str:
        return " ".join(str(s).split())

# ---------- Normalizacja identyfikatorów ----------
def _normalize_ident_bracketed(text: str) -> str:
    """Zamień na [Schema].[Object] jeśli wygląda jak schema.object; w innym wypadku zwróć oryginał."""
    if not text:
        return ""
    t = str(text).strip().rstrip(",;")
    t = t.split()[0]  # zetnij alias po spacji
    # [S].[O]
    m = re.match(r"^\[([^\[\]]+)\]\.\[([^\[\]]+)\]$", t)
    if m:
        return f"[{m.group(1)}].[{m.group(2)}]"
    # [S].O
    m = re.match(r"^\[([^\[\]]+)\]\.([A-Za-z0-9_]+)$", t)
    if m:
        return f"[{m.group(1)}].[{m.group(2)}]"
    # S.[O]
    m = re.match(r"^([A-Za-z0-9_]+)\.\[([^\[\]]+)\]$", t)
    if m:
        return f"[{m.group(1)}].[{m.group(2)}]"
    # S.O
    m = re.match(r"^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)$", t)
    if m:
        return f"[{m.group(1)}].[{m.group(2)}]"
    return t

def _same_object(a: str, b: str) -> bool:
    return _normalize_ident_bracketed(a).lower() == _normalize_ident_bracketed(b).lower()

# ---------- Purpose (neutralny, bez twardych nazw) ----------
def _infer_purpose_neutral(payload: Dict[str, Any]) -> str:
    obj = payload.get("object") or payload.get("obj") or ""
    writes = payload.get("writes_to") or []
    filters = payload.get("filters") or {}

    parts: List[str] = []
    if any((w.get("op","").upper()=="INSERT") for w in writes):
        parts.append("wstawia rekordy")
    if any((w.get("op","").upper()=="UPDATE") for w in writes):
        parts.append("aktualizuje statusy/rekordy")

    comp_txt = " ".join((filters.get("comparisons") or []))
    comp_nospace = comp_txt.replace(" ", "").lower()
    if "dateadd(minute,-15,getdate())" in comp_nospace or "dateadd(minute,-15,current_timestamp" in comp_nospace:
        parts.append("stosuje leasing 15 min przy przetwarzaniu")

    equals_txt = " ".join((filters.get("equals") or []))
    in_txt = " ".join((filters.get("in") or []))
    eq_low = equals_txt.lower()
    in_up = in_txt.replace(" ", "").upper()
    comp_low = comp_txt.lower()
    if (("STATUSIN('R','P')" in in_up or "STATUSIN('P','R')" in in_up)
        and "filename" in eq_low
        and " !=" in comp_low):
        parts.append("eliminuje duplikaty po nazwie pliku w obrębie przetworzonych/aktywnych")

    if not parts:
        parts.append("przetwarza dane (SELECT/IF/INSERT/UPDATE)")

    prefix = "Procedura" if obj else "Obiekt"
    return f"{prefix} {obj}: " + "; ".join(parts)

# ---------- Redukcje do formatu RAG ----------
def _params_min(params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for p in params or []:
        n = p.get("name") or p.get("n")
        t = p.get("type") or p.get("t")
        if n:
            out.append({"n": n, "t": t})
    return out

def _tx_min(tx: Dict[str, Any]) -> Dict[str, Any]:
    tx = tx or {}
    return {
        "beg": tx.get("begin_transactions", 0),
        "com": tx.get("commits", 0),
        "rol": tx.get("rollbacks", 0),
        "iso": tx.get("isolation_levels", []),
        "nolock": bool(tx.get("nolock_used", False)),
    }

def _writes_min(writes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for w in writes or []:
        tbl_raw = w.get("table")
        if not tbl_raw:
            continue
        tbl_text = str(tbl_raw).strip()
        if tbl_text.startswith("@") or tbl_text.startswith("#"):
            continue
        item = {
            "op": (w.get("op") or w.get("operation") or "").upper(),
            "table": _normalize_ident_bracketed(tbl_raw),
            "set": w.get("set_preview") or w.get("set"),
            "where": w.get("where_preview") or w.get("where"),
            "union_parts": w.get("union_parts"),
        }
        out.append(item)
    return out

def _flow_for_rag(payload: Dict[str, Any]):
    return payload.get("flow_tree") or payload.get("flow") or []

# ---------- Flags (OUTPUT-y, zmiany statusów, sygnały) ----------
def _flags_for_rag(payload: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    seen = set()
    def add(s: str):
        k = s.lower()
        if k not in seen:
            seen.add(k)
            flags.append(s)

    for p in (payload.get("parameters") or []):
        name = p.get("name") or p.get("n")
        typ = (p.get("type") or p.get("t") or "")
        if name and "OUTPUT" in str(typ).upper():
            add(f"OUTPUT:{name}")

    for w in (payload.get("writes_to") or []):
        tbl = w.get("table")
        setp = (w.get("set_preview") or w.get("set") or "") or ""
        if tbl and setp:
            m = re.search(r"\bStatus\s*=\s*'([^']+)'", setp, flags=re.I)
            if m:
                add(f"STATUS:{_normalize_ident_bracketed(tbl)}->'{m.group(1)}'")

    sql_strings = []
    for k in ("sql_no_comments", "raw_sql", "sql", "source", "tsql"):
        v = payload.get(k)
        if v:
            sql_strings.append(str(v))
    sql_nc = "\n".join(sql_strings)
    if re.search(r"\bRETURN\b", sql_nc, re.I):
        add("SIGNAL:RETURN")

    sets = ((payload.get("outputs_summary") or {}).get("sets")) or []
    for s in sets:
        v = s.get("var")
        if v:
            add(f"SIGNAL:{v}")

    for node in (payload.get("flow_tree") or []):
        for branch in ("then", "else"):
            for act in (node.get(branch) or []):
                step = (act.get("step") or "").upper()
                if step.startswith("RETURN"):
                    add("SIGNAL:RETURN")
    return flags

# ---------- Alias detection ----------
_ALIAS_CLAUSE = re.compile(
    r"\b(?:FROM|JOIN)\s+"
    r"(?P<table>(?:\[[^\]]+\]|\w+)(?:\.(?:\[[^\]]+\]|\w+))?)"
    r"(?:\s+AS)?\s+"
    r"(?P<alias>\[[^\]]+\]|\w+)"
    r"(?:\s+WITH\s*\([^)]+\))?",
    flags=re.IGNORECASE
)

def _collect_aliases(sql_text: str) -> Set[str]:
    aliases: Set[str] = set()
    for m in _ALIAS_CLAUSE.finditer(sql_text or ""):
        alias = m.group("alias")
        if not alias:
            continue
        alias = alias.strip()
        if alias.startswith("[") and alias.endswith("]"):
            alias = alias[1:-1]
        # pomijamy typowe słowa kluczowe
        if alias.upper() in {"WITH","NOLOCK","HOLDLOCK","ROWLOCK"}:
            continue
        # alias ma być pojedynczym tokenem bez kropki
        if "." in alias:
            continue
        aliases.add(alias.lower())
    return aliases

# ---------- Deps: writes + skan SQL (z odfiltrowaniem aliasów i funkcji) ----------
_SQL_FROMLIKE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO|DELETE\s+FROM)\s+([^\s,;]+)",
    flags=re.IGNORECASE
)

# dopasowanie S.O które NIE jest zmienną (@) ani wywołaniem funkcji/metody (…()
_NONBRACKET_SO = re.compile(
    r"(?<!@)\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()"
)

def _deps_fallback(payload: Dict[str, Any]) -> List[str]:
    out: Set[str] = set()
    obj = payload.get("object") or payload.get("obj") or ""

    sql_strings = []
    for k in ("sql_no_comments", "raw_sql", "sql", "source", "tsql"):
        v = payload.get(k)
        if v:
            sql_strings.append(str(v))
    sql_nc = "\n".join(sql_strings)

    aliases = _collect_aliases(sql_nc)

    # 1) z writes_to
    for w in (payload.get("writes_to") or []):
        tbl = _normalize_ident_bracketed(w.get("table"))
        if tbl and not tbl.startswith("@") and not tbl.startswith("#") and not _same_object(tbl, obj):
            out.add(tbl)

    # 2) FROM/JOIN/UPDATE/INTO
    for m in _SQL_FROMLIKE.finditer(sql_nc):
        token = (m.group(1) or "").strip().rstrip(",;")
        if not token or token.startswith("("):
            continue
        # odetnij alias po spacji
        token = token.split()[0]
        cand = _normalize_ident_bracketed(token)
        # odfiltruj zmienne i aliasy
        if cand.startswith("@") or cand.startswith("#"):
            continue
        left = cand.strip("[]").split(".")[0] if "." in cand else cand.strip("[]")
        if left.lower() in aliases:
            continue
        if "." not in cand:   # interesuje nas schema.table
            continue
        if not _same_object(cand, obj):
            out.add(cand)

    # 3) surowy skan S.O (bez @ i bez wywołań funkcji)
    for m in _NONBRACKET_SO.finditer(sql_nc):
        left, right = m.group(1), m.group(2)
        if left.lower() in aliases:
            continue
        cand = _normalize_ident_bracketed(f"{left}.{right}")
        if "." not in cand:
            continue
        if not _same_object(cand, obj):
            out.add(cand)

    # 4) skan wzorców z nawiasami kwadratowymi
    for pat in (
        r"\[([^\[\]]+)\]\.\[([^\[\]]+)\]",
        r"\[([^\[\]]+)\]\.([A-Za-z0-9_]+)",
        r"([A-Za-z0-9_]+)\.\[([^\[\]]+)\]",
    ):
        for m in re.finditer(pat, sql_nc):
            left, right = m.group(1), m.group(2)
            if left.lower() in aliases:
                continue
            cand = _normalize_ident_bracketed(f"{left}.{right}")
            # jeśli to wygląda na funkcję/metodę (tuż po prawej nawias), pomijamy
            tail_idx = m.end()
            if tail_idx < len(sql_nc) and re.match(r"\s*\(", sql_nc[tail_idx:]):
                continue
            if "." in cand and not _same_object(cand, obj):
                out.add(cand)

    # tylko realne schema.table
    filtered = sorted(x for x in out if re.match(r"^\[[^\[\]]+\]\.\[[^\[\]]+\]$", x))
    return filtered

# ---------- Public API ----------
def make_compact(payload: Dict[str, Any], **_ignore):
    obj = payload.get("object") or payload.get("obj") or ""
    purpose = _infer_purpose_neutral(payload)
    return {
        "obj": obj,
        "purpose": purpose,
        "params": _params_min(payload.get("parameters") or []),
        "dml": payload.get("dml_ops") or [],
        "deps": _deps_fallback(payload),
        "tx": _tx_min(payload.get("tx_meta") or {}),
        "flow": _flow_for_rag(payload),
        "writes": _writes_min(payload.get("writes_to") or []),
        "flags": _flags_for_rag(payload),
        "filters": payload.get("filters") or {},
    }

def human_summary(payload: Dict[str, Any]) -> str:
    obj = payload.get("object") or payload.get("obj") or "(unknown)"
    purpose = _infer_purpose_neutral(payload)
    deps = ", ".join(_deps_fallback(payload))
    tx = payload.get("tx_meta") or {}
    flow = payload.get("flow_tree") or payload.get("flow") or []
    head = f"{obj} — {purpose}".strip(" —")
    txs = f"TX: beg={tx.get('begin_transactions',0)} com={tx.get('commits',0)} rol={tx.get('rollbacks',0)}"
    flow_txt = "\n".join(f"  - {one_line(str(s))}" for s in (flow[:10] if flow else []))
    parts = [head, txs]
    if deps:
        parts.append(f"Deps: {deps}")
    if flow_txt:
        parts.append("Flow:\n" + flow_txt)
    return "\n".join(parts)
