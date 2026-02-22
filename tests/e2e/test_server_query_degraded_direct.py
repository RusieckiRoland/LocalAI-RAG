# tests/e2e/test_server_query_degraded_direct.py

from __future__ import annotations

import importlib
import sys
from typing import Any, Dict

import pytest


def _stub_module(monkeypatch: pytest.MonkeyPatch, module_name: str, attrs: Dict[str, Any]) -> None:
    """
    Insert a lightweight stub module into sys.modules.
    """
    import types

    m = types.ModuleType(module_name)
    for k, v in attrs.items():
        setattr(m, k, v)

    monkeypatch.setitem(sys.modules, module_name, m)


def test_query_endpoint_works_with_stubbed_runner(monkeypatch: pytest.MonkeyPatch):
    """
    E2E-ish: server should respond to /search even when the pipeline runner is stubbed.
    This ensures the HTTP surface works and the server module can be imported without heavy deps.
    """

    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("API_TOKEN", "")

    # Stub translators (avoid torch)
    _stub_module(monkeypatch, "common.markdown_translator_en_pl", {"MarkdownTranslator": lambda *a, **k: object()})
    _stub_module(
        monkeypatch,
        "common.translator_pl_en",
        {
            "TranslatorPlEn": lambda *a, **k: object(),
            "Translator": lambda *a, **k: object(),
        },
    )

    # Stub model (avoid weights)
    _stub_module(monkeypatch, "code_query_engine.model", {"Model": lambda *a, **k: object()})

    # Stub logger (harmless)
    _stub_module(monkeypatch, "code_query_engine.log_utils", {"InteractionLogger": lambda *a, **k: object()})

    # Stub DynamicPipelineRunner so /search returns deterministically without relying on pipeline files
    class _DummyRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self, **kwargs: Any):
            # runner.run is expected to return either tuple or dict; support both.
            return ("E2E OK", "DIRECT", ["boot"], "model_input_stub")

    _stub_module(monkeypatch, "code_query_engine.dynamic_pipeline", {"DynamicPipelineRunner": _DummyRunner})

    module_name = "code_query_engine.query_server_dynamic"
    if module_name in sys.modules:
        del sys.modules[module_name]

    server_mod = importlib.import_module(module_name)
    app = getattr(server_mod, "app")

    client = app.test_client()

    payload: Dict[str, Any] = {
        "query": "hello",
        "consultant": "e2e_smoke",
        "branch": "develop",
        "translateChat": False,
        "session_id": "test-session",
    }

    resp = client.post("/search/dev", json=payload)
    assert resp.status_code == 200

    data = resp.get_json()
    assert isinstance(data, dict)

    assert data.get("results") == "E2E OK"
    assert data.get("session_id") == "test-session"
    assert data.get("consultant") == "e2e_smoke"
