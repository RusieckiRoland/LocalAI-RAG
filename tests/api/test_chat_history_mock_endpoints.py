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


def test_chat_history_patch_important_and_soft_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    qsd = _import_server(monkeypatch)
    monkeypatch.setattr(qsd, "_mock_sql_enabled", True, raising=False)
    qsd._history_sessions.clear()
    qsd._history_messages.clear()
    client = qsd.app.test_client()

    create = client.post("/chat-history/sessions", json={"title": "Important Chat"}, headers=_auth_headers())
    assert create.status_code == 200
    session_id = create.get_json()["sessionId"]

    patch_important = client.patch(
        f"/chat-history/sessions/{session_id}",
        json={"important": True},
        headers=_auth_headers(),
    )
    assert patch_important.status_code == 200
    patched = patch_important.get_json()
    assert patched["important"] is True
    assert patched["status"] == "active"

    listed = client.get("/chat-history/sessions?limit=10", headers=_auth_headers())
    assert listed.status_code == 200
    items = listed.get_json()["items"]
    assert items and items[0]["important"] is True

    patch_deleted = client.patch(
        f"/chat-history/sessions/{session_id}",
        json={"softDeleted": True},
        headers=_auth_headers(),
    )
    assert patch_deleted.status_code == 200
    deleted = patch_deleted.get_json()
    assert deleted["status"] == "soft_deleted"
    assert deleted["softDeletedAt"] is not None

    listed_after_delete = client.get("/chat-history/sessions?limit=10", headers=_auth_headers())
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.get_json()["items"] == []

    get_deleted = client.get(f"/chat-history/sessions/{session_id}", headers=_auth_headers())
    assert get_deleted.status_code == 404


def test_chat_history_sessions_support_query_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    qsd = _import_server(monkeypatch)
    monkeypatch.setattr(qsd, "_mock_sql_enabled", True, raising=False)
    qsd._history_sessions.clear()
    qsd._history_messages.clear()
    client = qsd.app.test_client()

    r1 = client.post("/chat-history/sessions", json={"title": "Category in Nop"}, headers=_auth_headers())
    r2 = client.post("/chat-history/sessions", json={"title": "Tax in ERP"}, headers=_auth_headers())
    assert r1.status_code == 200
    assert r2.status_code == 200

    res = client.get("/chat-history/sessions?limit=50&q=category", headers=_auth_headers())
    assert res.status_code == 200
    items = res.get_json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Category in Nop"
