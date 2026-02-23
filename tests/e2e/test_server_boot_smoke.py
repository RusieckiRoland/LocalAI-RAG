from __future__ import annotations

import importlib
import sys
import types
from typing import Any, Optional

import pytest


def _stub_module(monkeypatch: pytest.MonkeyPatch, name: str, attrs: dict[str, Any]) -> None:
    """
    Install a lightweight stub module into sys.modules so imports won't pull heavy deps (torch, sentence-transformers).
    """
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)


def _extract_searcher_status(payload: Any) -> tuple[Optional[bool], str]:
    """
    Be tolerant to minor shape differences of /health response.
    Returns (searcher_ok, error_message).
    """
    if not isinstance(payload, dict):
        return None, ""

    for k in ("searcher_ok", "search_ok", "searcherOk"):
        if k in payload:
            ok = payload.get(k)
            err = str(payload.get("searcher_error") or payload.get("error") or "")
            return (bool(ok) if ok is not None else None), err

    nested = payload.get("searcher")
    if isinstance(nested, dict):
        ok = nested.get("ok")
        err = str(nested.get("error") or "")
        return (bool(ok) if ok is not None else None), err

    return None, ""

