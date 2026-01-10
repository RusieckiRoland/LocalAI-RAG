# code_query_engine/pipeline/query_parsers/jsonish_query_parser.py
from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, List, Tuple

from .base_query_parser import BaseQueryParser, QueryParseResult


_RE_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_RE_UNQUOTED_KEY = re.compile(r"(?P<prefix>[{,]\s*)(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)\s*:")
_RE_EQUAL_ASSIGN = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)\s*=\s*")


def _strip_code_fences(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```") and t.endswith("```"):
        t = t[3:-3].strip()
        # optional language label
        t = re.sub(r"^[A-Za-z0-9_\-]+\n", "", t)
    return t.strip()


def _coerce_dict(obj: Any) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if obj is None:
        return {}, warnings
    if isinstance(obj, dict):
        return obj, warnings
    warnings.append(f"filters was not a dict (got {type(obj).__name__}); ignoring.")
    return {}, warnings


class JsonishQueryParser(BaseQueryParser):
    """
    Best-effort parser for payloads that are intended to be JSON objects:
        {"query":"...","filters":{...}}

    It tries:
    - json.loads
    - ast.literal_eval (single quotes, Python dict style)
    - simple repairs: quote keys, remove trailing commas, replace '=' with ':'
    """

    @property
    def parser_id(self) -> str:
        return "jsonish_v1"

    def parse(self, payload: str) -> QueryParseResult:
        warnings: List[str] = []
        raw = _strip_code_fences(payload)

        if not raw.strip():
            return QueryParseResult(query="", filters={}, warnings=["empty payload"])

        obj, w = self._try_parse_object(raw)
        warnings.extend(w)

        # If we still don't have a dict, treat the whole payload as the query.
        if not isinstance(obj, dict):
            return QueryParseResult(query=raw.strip(), filters={}, warnings=warnings)

        query_val = obj.get("query")
        if isinstance(query_val, str):
            query = query_val.strip()
        else:
            if query_val is not None:
                warnings.append(f"'query' was not a string (got {type(query_val).__name__}); using raw payload as query.")
            query = raw.strip()

        filters_obj = obj.get("filters", {})
        filters, w2 = _coerce_dict(filters_obj)
        warnings.extend(w2)

        # Normalize keys to strings.
        norm_filters: Dict[str, Any] = {}
        for k, v in (filters or {}).items():
            ks = str(k).strip()
            if not ks:
                continue
            norm_filters[ks] = v

        return QueryParseResult(query=query, filters=norm_filters, warnings=warnings)

    def _try_parse_object(self, raw: str) -> Tuple[Any, List[str]]:
        warnings: List[str] = []

        # First: as-is JSON.
        obj = self._try_json(raw)
        if obj is not None:
            return obj, warnings

        # Repairs
        fixed = raw.strip()

        # If it's missing outer braces but looks like key/value pairs, wrap it.
        if not fixed.startswith("{") and ("query" in fixed or "filters" in fixed):
            fixed = "{" + fixed + "}"
            warnings.append("wrapped payload in '{...}'")

        # Replace '=' assignments (query=..., filters=...) with ':'.
        if "=" in fixed and ":" not in fixed:
            fixed = _RE_EQUAL_ASSIGN.sub(lambda m: f'{m.group("key")}: ', fixed)
            warnings.append("replaced '=' with ':'")

        # Quote unquoted keys (JSON requires quotes).
        fixed2 = _RE_UNQUOTED_KEY.sub(lambda m: f'{m.group("prefix")}"{m.group("key")}":', fixed)
        if fixed2 != fixed:
            fixed = fixed2
            warnings.append("quoted unquoted keys")

        # Remove trailing commas before closing braces/brackets.
        fixed2 = _RE_TRAILING_COMMA.sub(r"\1", fixed)
        if fixed2 != fixed:
            fixed = fixed2
            warnings.append("removed trailing commas")

        # Second: try JSON after repairs.
        obj = self._try_json(fixed)
        if obj is not None:
            return obj, warnings

        # Third: Python literal style (single quotes, etc.).
        try:
            obj = ast.literal_eval(fixed)
            return obj, warnings + ["parsed via ast.literal_eval"]
        except Exception:
            return None, warnings + ["could not parse payload as object"]

    def _try_json(self, s: str) -> Any:
        try:
            return json.loads(s)
        except Exception:
            return None
