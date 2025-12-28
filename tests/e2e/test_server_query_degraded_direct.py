from __future__ import annotations

import importlib
import sys
import types
from typing import Any, Dict

import pytest


def _stub_module(monkeypatch: pytest.MonkeyPatch, name: str, attrs: dict[str, Any]) -> None:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)


def test_query_endpoint_works_in_degraded_mode(monkeypatch: pytest.MonkeyPatch):
    """
    E2E-ish: when unified index can't be loaded at startup, server should still respond to /query
    (e.g., DIRECT pipelines) and return a well-formed JSON response.
    """

    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("API_TOKEN", "")

    # Force unified index loader failure (missing faiss)
    def _fail_load_unified_search(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("FAISS index not found: /tmp/x/unified_index.faiss")

    _stub_module(monkeypatch, "vector_db.unified_index_loader", {"load_unified_search": _fail_load_unified_search})

    # Stub translators (avoid torch)
    _stub_module(monkeypatch, "common.markdown_translator_en_pl", {"MarkdownTranslator": lambda *a, **k: object()})
    _stub_module(monkeypatch, "common.translator_pl_en", {"TranslatorPlEn": lambda *a, **k: object(), "Translator": lambda *a, **k: object()})

    # Stub model (avoid weights)
    _stub_module(monkeypatch, "code_query_engine.model", {"Model": lambda *a, **k: object()})

    # Stub logger (harmless)
    _stub_module(monkeypatch, "code_query_engine.log_utils", {"InteractionLogger": lambda *a, **k: object()})

    # Stub DynamicPipelineRunner so /query returns deterministically without relying on pipeline files
    class _DummyRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self, **kwargs: Any):
            # runner.run is expected to return either tuple or dict; support both.
            return ("E2E OK (degraded)", "DIRECT", ["boot"], "model_input_stub")

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

    resp = client.post("/query", json=payload)
    assert resp.status_code == 200

    data = resp.get_json(silent=True) or {}
    # Be tolerant to response shape drift (some versions use "answer", some "results")
    answer = data.get("answer") or data.get("results") or ""
    assert "E2E OK" in str(answer)
