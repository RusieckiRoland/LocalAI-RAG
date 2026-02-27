from __future__ import annotations

import importlib
import os
import sys
import types
from typing import Any, Dict

import pytest


def _stub_module(monkeypatch: pytest.MonkeyPatch, module_name: str, attrs: Dict[str, Any]) -> None:
    mod = types.ModuleType(module_name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    monkeypatch.setitem(sys.modules, module_name, mod)


def _import_query_server_dynamic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("IDP_AUTH_ENABLED", "0")
    if not os.getenv("APP_PROFILE"):
        monkeypatch.setenv("APP_PROFILE", "dev")

    _stub_module(monkeypatch, "common.markdown_translator_en_pl", {"MarkdownTranslator": lambda *a, **k: object()})
    _stub_module(monkeypatch, "common.translator_pl_en", {"TranslatorPlEn": lambda *a, **k: object(), "Translator": lambda *a, **k: object()})
    _stub_module(monkeypatch, "code_query_engine.model", {"Model": lambda *a, **k: object()})
    _stub_module(monkeypatch, "code_query_engine.log_utils", {"InteractionLogger": lambda *a, **k: object()})

    class _DummyRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self, **kwargs: Any):
            return ("OK", "DIRECT", ["boot"], "stub")

    _stub_module(monkeypatch, "code_query_engine.dynamic_pipeline", {"DynamicPipelineRunner": _DummyRunner})
    _stub_module(monkeypatch, "vector_db.weaviate_client", {"get_settings": lambda: {}, "create_client": lambda settings: None})

    sys.modules.pop("code_query_engine.query_server_dynamic", None)
    return importlib.import_module("code_query_engine.query_server_dynamic")


def test_search_prod_requires_token_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "")
    qsd = _import_query_server_dynamic(monkeypatch)

    client = qsd.app.test_client()
    res = client.post("/search", json={"consultant": "rejewski", "query": "hi"})

    assert res.status_code == 503
    assert b"server auth is not configured" in res.data


def test_search_prod_requires_valid_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "top-secret")
    qsd = _import_query_server_dynamic(monkeypatch)

    client = qsd.app.test_client()
    res_bad = client.post("/search", json={"consultant": "rejewski", "query": "hi"})
    assert res_bad.status_code == 401

    res_ok = client.post(
        "/search",
        json={"consultant": "rejewski", "query": "hi"},
        headers={"Authorization": "Bearer top-secret"},
    )
    assert res_ok.status_code == 200

    check_bad = client.get("/auth-check")
    assert check_bad.status_code == 401

    check_ok = client.get("/auth-check", headers={"Authorization": "Bearer top-secret"})
    assert check_ok.status_code == 200


def test_dev_allow_no_auth_allows_requests_without_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "top-secret")
    monkeypatch.setenv("APP_PROFILE", "dev")
    monkeypatch.setenv("DEV_ALLOW_NO_AUTH", "true")
    qsd = _import_query_server_dynamic(monkeypatch)

    client = qsd.app.test_client()
    res = client.post("/search", json={"consultant": "rejewski", "query": "hi"})
    assert res.status_code == 401

    res2 = client.post(
        "/search",
        json={"consultant": "rejewski", "query": "hi"},
        headers={"Authorization": "Bearer dev-user:john_kowalski"},
    )

    assert res2.status_code == 200


def test_search_prod_uses_idp_validation_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    qsd = _import_query_server_dynamic(monkeypatch)

    monkeypatch.setattr(qsd, "_idp_auth_is_active", lambda: True)
    monkeypatch.setattr(qsd, "_validate_idp_bearer", lambda auth_header: None)

    client = qsd.app.test_client()
    res = client.post("/search", json={"consultant": "rejewski", "query": "hi"})
    assert res.status_code == 200


def test_search_prod_returns_idp_error(monkeypatch: pytest.MonkeyPatch) -> None:
    qsd = _import_query_server_dynamic(monkeypatch)

    monkeypatch.setattr(qsd, "_idp_auth_is_active", lambda: True)
    monkeypatch.setattr(qsd, "_validate_idp_bearer", lambda auth_header: (qsd.jsonify({"ok": False, "error": "unauthorized"}), 401))

    client = qsd.app.test_client()
    res = client.post("/search", json={"consultant": "rejewski", "query": "hi"})
    assert res.status_code == 401


def test_app_config_requires_bearer_when_no_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "top-secret")
    qsd = _import_query_server_dynamic(monkeypatch)

    client = qsd.app.test_client()
    bad = client.get("/app-config")
    assert bad.status_code == 401

    ok = client.get("/app-config", headers={"Authorization": "Bearer top-secret"})
    assert ok.status_code == 200


def test_dev_allow_no_auth_is_forbidden_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PROFILE", "prod")
    monkeypatch.setenv("DEV_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("IDP_AUTH_ENABLED", "0")

    with pytest.raises(RuntimeError):
        _import_query_server_dynamic(monkeypatch)
