import importlib
import sys
import types

import pytest


def _stub_module(monkeypatch: pytest.MonkeyPatch, module_name: str, attrs: dict) -> None:
    mod = types.ModuleType(module_name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    monkeypatch.setitem(sys.modules, module_name, mod)


def _import_server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("IDP_AUTH_ENABLED", "0")
    monkeypatch.setenv("APP_DEVELOPMENT", "1")

    _stub_module(monkeypatch, "common.markdown_translator_en_pl", {"MarkdownTranslator": lambda *a, **k: object()})
    _stub_module(monkeypatch, "common.translator_pl_en", {"TranslatorPlEn": lambda *a, **k: object(), "Translator": lambda *a, **k: object()})
    _stub_module(monkeypatch, "code_query_engine.model", {"Model": lambda *a, **k: object()})
    _stub_module(monkeypatch, "code_query_engine.log_utils", {"InteractionLogger": lambda *a, **k: object()})

    class _DummyRunner:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, **kwargs):
            return ("OK", "DIRECT", ["boot"], "stub")

    _stub_module(monkeypatch, "code_query_engine.dynamic_pipeline", {"DynamicPipelineRunner": _DummyRunner})
    _stub_module(monkeypatch, "vector_db.weaviate_client", {"get_settings": lambda: {}, "create_client": lambda settings: None})

    sys.modules.pop("code_query_engine.query_server_dynamic", None)
    return importlib.import_module("code_query_engine.query_server_dynamic")


def _auth_headers(user: str = "dev-user-1") -> dict:
    return {"Authorization": f"Bearer dev-user:{user}"}


def test_chat_history_mock_endpoints_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    qsd = _import_server(monkeypatch)

    # Enable mock SQL history for this test run.
    monkeypatch.setattr(qsd, "_mock_sql_enabled", True, raising=False)
    qsd._history_sessions.clear()
    qsd._history_messages.clear()

    client = qsd.app.test_client()

    # Create session
    resp = client.post("/chat-history/sessions", json={"title": "T1"}, headers=_auth_headers())
    assert resp.status_code == 200
    session = resp.get_json()
    session_id = session["sessionId"]

    # Add message
    resp = client.post(
        f"/chat-history/sessions/{session_id}/messages",
        json={"q": "Q1", "a": "A1"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200

    # List sessions
    resp = client.get("/chat-history/sessions?limit=50", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["items"]
    assert data["items"][0]["sessionId"] == session_id

    # List messages
    resp = client.get(f"/chat-history/sessions/{session_id}/messages?limit=50", headers=_auth_headers())
    assert resp.status_code == 200
    msgs = resp.get_json()["items"]
    assert len(msgs) == 1
    assert msgs[0]["q"] == "Q1"
    assert msgs[0]["a"] == "A1"

    # History should be readable by pipeline service (durable fallback).
    svc = qsd._conversation_history_service
    out = svc.get_recent_qa_neutral(session_id=session_id, limit=10)
    assert out == {"Q1": "A1"}

    # Different user should not see it
    resp = client.get("/chat-history/sessions?limit=50", headers=_auth_headers("dev-user-2"))
    assert resp.status_code == 200
    assert resp.get_json()["items"] == []


def test_chat_history_unavailable_when_mock_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    qsd = _import_server(monkeypatch)
    monkeypatch.setattr(qsd, "_mock_sql_enabled", False, raising=False)
    client = qsd.app.test_client()

    resp = client.get("/chat-history/sessions?limit=10", headers=_auth_headers())
    assert resp.status_code == 503
