from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest


def _stub_module(monkeypatch: pytest.MonkeyPatch, name: str, attrs: dict[str, Any]) -> None:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)


def test_server_import_does_not_import_torch(monkeypatch: pytest.MonkeyPatch):
    """
    Contract test: importing the server module must NOT import torch at all.
    If someone introduces an import-time dependency on torch, this will catch it.
    """
    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("API_TOKEN", "")

    # Ensure clean state for the assertion
    sys.modules.pop("torch", None)

    # Stub modules that would otherwise import torch
    class _DummyMarkdownTranslator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _DummyTranslatorPlEn:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    _stub_module(monkeypatch, "common.markdown_translator_en_pl", {"MarkdownTranslator": _DummyMarkdownTranslator})
    _stub_module(monkeypatch, "common.translator_pl_en", {"TranslatorPlEn": _DummyTranslatorPlEn, "Translator": _DummyTranslatorPlEn})

    

    # Stub model/logger to avoid heavyweight init
    _stub_module(monkeypatch, "code_query_engine.model", {"Model": lambda *a, **k: object()})
    _stub_module(monkeypatch, "code_query_engine.log_utils", {"InteractionLogger": lambda *a, **k: object()})

    module_name = "code_query_engine.query_server_dynamic"
    if module_name in sys.modules:
        del sys.modules[module_name]

    importlib.import_module(module_name)

    # The whole point:
    assert "torch" not in sys.modules, "Server import must not import torch"
