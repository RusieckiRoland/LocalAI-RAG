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


def test_server_boots_even_when_unified_index_is_missing(monkeypatch: pytest.MonkeyPatch):
    """
    Boot-smoke: importing the Flask server module must NOT crash
    when unified_index.faiss is missing. Instead, /health must report
    searcher_ok=false and contain a readable error message.

    This test MUST NOT import modules that pull torch/sentence-transformers.
    We stub them via sys.modules before importing the server.
    """

    # Ensure we do not accidentally try to connect Redis during import.
    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("API_TOKEN", "")

    # --- Stub heavy/fragile deps BEFORE importing the server module ---

    # 1) Stub unified index loader (real one imports sentence-transformers -> torch)
    def _fake_load_unified_search(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("FAISS index not found: /tmp/x/unified_index.faiss")

    _stub_module(
        monkeypatch,
        "vector_db.unified_index_loader",
        {"load_unified_search": _fake_load_unified_search},
    )

    # 2) Stub translators (real markdown translator imports torch)
    class _DummyMarkdownTranslator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def translate(self, text: str) -> str:
            return text

    class _DummyTranslatorPlEn:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def translate(self, text: str) -> str:
            return text

    _stub_module(
        monkeypatch,
        "common.markdown_translator_en_pl",
        {"MarkdownTranslator": _DummyMarkdownTranslator},
    )
    _stub_module(
        monkeypatch,
        "common.translator_pl_en",
        {"TranslatorPlEn": _DummyTranslatorPlEn, "Translator": _DummyTranslatorPlEn},
    )

    # 3) Stub model (avoid loading real weights during import)
    class _DummyModel:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def ask(self, *args: Any, **kwargs: Any) -> str:
            return "[DIRECT:]"

    _stub_module(monkeypatch, "code_query_engine.model", {"Model": _DummyModel})

    # 4) Stub logger (keep it harmless even if unused)
    class _DummyLogger:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def info(self, *args: Any, **kwargs: Any) -> None:
            pass

        def warning(self, *args: Any, **kwargs: Any) -> None:
            pass

        def error(self, *args: Any, **kwargs: Any) -> None:
            pass

    _stub_module(monkeypatch, "code_query_engine.log_utils", {"InteractionLogger": _DummyLogger})

    # --- Import server module (must not crash) ---
    module_name = "code_query_engine.query_server_dynamic"
    if module_name in sys.modules:
        del sys.modules[module_name]

    server_mod = importlib.import_module(module_name)

    assert hasattr(server_mod, "app"), "Server module must expose Flask 'app'"
    app = getattr(server_mod, "app")

    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200

    payload = resp.get_json(silent=True)
    ok, err = _extract_searcher_status(payload)

    assert ok is False, f"/health must report searcher_ok=false, got payload={payload!r}"
    err_l = (err or "").lower()
    assert ("unified_index" in err_l) or ("faiss" in err_l), f"Expected readable error, got: {err!r}"
