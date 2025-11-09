# api.py — public entrypoints: summarize_tsql(), make_compact(), human_summary()
from typing import Dict, Any, List

from .utils import strip_comments, normalize_ws
from .ddl_extractors import build_table_meta
from .emit import make_compact as emit_make_compact, human_summary as emit_human_summary

# Parsowanie i analiza — mogą rzucać wyjątki, więc używamy try/except niżej
from .parsing import (
    parse_proc_header, parse_table_header, parse_params, parse_ctes,
    find_select_blocks, _disambiguate_select_aliases, infer_result_columns,
    parse_dml_ops, parse_writes, detect_flags, parse_sets, find_pagination,
    tx_metadata, collect_sources, _disambiguate_sources, list_dependencies,
)
from .analysis import (
    build_flow_tree, summarize_filters_global, summarize_filters,
)

# --- API kompatybilne z resztą kodu ---
def make_compact(payload: Dict[str, Any], **kwargs) -> Any:
    # akceptujemy dowolne kwargs dla zgodności wstecznej (mode, minify, itp.)
    return emit_make_compact(payload, **kwargs)

def human_summary(payload: Dict[str, Any]) -> str:
    return emit_human_summary(payload)

# --- Główny punkt wejścia ---
def summarize_tsql(tsql: str) -> Dict[str, Any]:
    """Zbuduj pełny payload dla danego T-SQL (procedura lub CREATE TABLE)."""
    raw = tsql
    sql_nc = normalize_ws(strip_comments(raw))

    payload: Dict[str, Any] = {
        "sql_no_comments": sql_nc,
        "object": "",
        "parameters": [],
        "dml_ops": [],
        "writes_to": [],
        "outputs_summary": {},
        "result_columns": [],
        "tx_meta": {},
        "flow_tree": [],
        "filters": {},
        "dependencies": [],
        "purpose": "",
    }

    # 1) Nagłówek procedury lub CREATE TABLE
    obj = ""
    param_block = ""
    try:
        obj, param_block = parse_proc_header(sql_nc)
    except Exception:
        obj, param_block = "", ""

    is_table = False
    if not obj:
        try:
            tname = parse_table_header(sql_nc)
        except Exception:
            tname = ""
        if tname:
            obj = tname
            param_block = ""
            is_table = True

    payload["object"] = obj

    # 2) Parametry (dla procedur)
    if not is_table:
        try:
            payload["parameters"] = parse_params(param_block)
        except Exception:
            payload["parameters"] = []

    # 3) Analiza treści (procedury)
    if not is_table:
        try:
            ctes = parse_ctes(sql_nc)
        except Exception:
            ctes = []

        try:
            selects = find_select_blocks(sql_nc)
        except Exception:
            selects = []
        try:
            selects = _disambiguate_select_aliases(selects)
        except Exception:
            pass

        try:
            payload["result_columns"] = infer_result_columns(selects)
        except Exception:
            payload["result_columns"] = []

        try:
            payload["dml_ops"] = parse_dml_ops(sql_nc)
        except Exception:
            payload["dml_ops"] = []

        try:
            payload["writes_to"] = parse_writes(sql_nc)
        except Exception:
            payload["writes_to"] = []

        # outputs / flags
        outs = {"flags": [], "sets": [], "pagination": {}}
        try:
            outs["flags"] = detect_flags(sql_nc)
        except Exception:
            pass
        try:
            outs["sets"] = parse_sets(sql_nc)
        except Exception:
            pass
        try:
            outs["pagination"] = find_pagination(sql_nc)
        except Exception:
            pass
        payload["outputs_summary"] = outs

        # TX i flow
        try:
            payload["tx_meta"] = tx_metadata(sql_nc)
        except Exception:
            payload["tx_meta"] = {}

        try:
            payload["flow_tree"] = build_flow_tree(sql_nc)
        except Exception:
            payload["flow_tree"] = []

        # Filtry
        try:
            payload["filters"] = summarize_filters(sql_nc)
        except Exception:
            try:
                payload["filters"] = summarize_filters_global(sql_nc)
            except Exception:
                payload["filters"] = {}

        # Zależności (deps)
        try:
            sources = collect_sources(sql_nc)
        except Exception:
            sources = []
        try:
            sources = _disambiguate_sources(sources, payload.get("writes_to") or [])
        except Exception:
            pass
        try:
            payload["dependencies"] = list_dependencies(sources, payload.get("writes_to") or [])
        except Exception:
            payload["dependencies"] = []

        # Purpose (neutralny, bez hardcodów nazw)
        try:
            from .analysis import infer_purpose as _infer
            payload["purpose"] = _infer(payload)
        except Exception:
            payload["purpose"] = f"Procedura {obj}: przetwarza dane (SELECT/INSERT/UPDATE)."

        return payload

    # 4) CREATE TABLE (DDL)
    payload["flow_tree"] = [{"step": "CREATE TABLE"}]
    payload["purpose"] = f"Tabela {obj}: definicja kolumn/kluczy."
    try:
        payload["ddl_meta"] = build_table_meta(sql_nc)
    except Exception:
        payload["ddl_meta"] = {}
    return payload

__all__ = ["summarize_tsql", "make_compact", "human_summary"]
