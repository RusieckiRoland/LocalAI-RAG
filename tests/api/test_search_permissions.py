import importlib
import sys
import types
from typing import Any, Dict

from server.auth.user_access import UserAccessContext


def _stub_module(module_name: str, attrs: Dict[str, Any]) -> None:
    mod = types.ModuleType(module_name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[module_name] = mod


def _import_query_server_dynamic(monkeypatch):
    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("APP_PROFILE", "dev")
    monkeypatch.setenv("DEV_ALLOW_NO_AUTH", "true")

    # Prevent heavyweight model init (llama-cpp) during module import.
    _stub_module("common.markdown_translator_en_pl", {"MarkdownTranslator": lambda *a, **k: object()})
    _stub_module("common.translator_pl_en", {"TranslatorPlEn": lambda *a, **k: object(), "Translator": lambda *a, **k: object()})
    _stub_module("code_query_engine.model", {"Model": lambda *a, **k: object()})
    _stub_module("code_query_engine.log_utils", {"InteractionLogger": lambda *a, **k: object()})

    class _DummyRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self, **kwargs: Any):
            return ("OK", "DIRECT", ["boot"], "stub")

    _stub_module("code_query_engine.dynamic_pipeline", {"DynamicPipelineRunner": _DummyRunner})

    fake_weaviate = types.SimpleNamespace(
        get_settings=lambda: {},
        create_client=lambda settings: None,
    )
    sys.modules["vector_db.weaviate_client"] = fake_weaviate
    sys.modules.pop("code_query_engine.query_server_dynamic", None)

    module = importlib.import_module("code_query_engine.query_server_dynamic")
    return module


def test_search_denies_pipeline_not_allowed(monkeypatch):
    qsd = _import_query_server_dynamic(monkeypatch)

    class _Provider:
        def resolve(self, *, user_id, token, session_id, claims=None):
            return UserAccessContext(
                user_id=None,
                is_anonymous=True,
                group_ids=[],
                allowed_pipelines=["ada"],
                allowed_commands=[],
                acl_tags_any=[],
            )

    qsd._user_access_provider = _Provider()
    qsd._pipeline_snapshot_store = None
    qsd._snapshot_registry = None

    client = qsd.app.test_client()
    res = client.post(
        "/search",
        json={"consultant": "rejewski", "query": "hi"},
        headers={"Authorization": "Bearer dev-user:john_kowalski"},
    )

    assert res.status_code == 403


def test_search_response_uses_runner_final_output_as_results(monkeypatch):
    qsd = _import_query_server_dynamic(monkeypatch)

    class _Provider:
        def resolve(self, *, user_id, token, session_id, claims=None):
            return UserAccessContext(
                user_id=None,
                is_anonymous=True,
                group_ids=[],
                allowed_pipelines=[],
                allowed_commands=[],
                acl_tags_any=[],
            )

    qsd._user_access_provider = _Provider()
    qsd._pipeline_snapshot_store = None
    qsd._snapshot_registry = None

    client = qsd.app.test_client()
    res = client.post(
        "/search",
        json={"consultant": "rejewski", "query": "hi"},
        headers={"Authorization": "Bearer dev-user:john_kowalski"},
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["results"] == "OK"
    assert payload["translated"] == "stub"


def test_search_returns_400_for_unknown_snapshot_set(monkeypatch):
    qsd = _import_query_server_dynamic(monkeypatch)

    class _Provider:
        def resolve(self, *, user_id, token, session_id):
            return UserAccessContext(
                user_id=None,
                is_anonymous=True,
                group_ids=["developers"],
                allowed_pipelines=["rejewski"],
                allowed_commands=[],
                acl_tags_any=[],
            )

    class _PipelineStore:
        def get_snapshot_set_id(self, pipeline_name: str):
            return True, "set1"

    class _Registry:
        def fetch_snapshot_set(self, *, snapshot_set_id, repository):
            return None

    qsd._user_access_provider = _Provider()
    qsd._pipeline_snapshot_store = _PipelineStore()
    qsd._snapshot_registry = _Registry()

    client = qsd.app.test_client()
    res = client.post(
        "/search",
        json={"pipelineName": "rejewski", "consultant": "rejewski", "query": "hi"},
        headers={"Authorization": "Bearer dev-user:john_kowalski"},
    )

    assert res.status_code == 400
    assert b"unknown snapshot_set_id" in res.data


def test_search_denies_snapshot_not_in_snapshot_set(monkeypatch):
    qsd = _import_query_server_dynamic(monkeypatch)

    class _Provider:
        def resolve(self, *, user_id, token, session_id, claims=None):
            return UserAccessContext(
                user_id=None,
                is_anonymous=True,
                group_ids=["developers"],
                allowed_pipelines=["rejewski"],
                allowed_commands=[],
                acl_tags_any=[],
            )

    class _Registry:
        def list_snapshots(self, *, snapshot_set_id, repository):
            class _S:
                def __init__(self, id):
                    self.id = id
            return [_S("allowed-1"), _S("allowed-2")]

    qsd._user_access_provider = _Provider()
    qsd._pipeline_snapshot_store = None
    qsd._snapshot_registry = _Registry()

    client = qsd.app.test_client()
    res = client.post(
        "/search",
        json={
            "pipelineName": "rejewski",
            "consultant": "rejewski",
            "query": "hi",
            "snapshot_set_id": "set1",
            "snapshot_id": "not-allowed",
        },
        headers={"Authorization": "Bearer dev-user:john_kowalski"},
    )

    assert res.status_code == 400
    assert b"snapshot_id is not allowed in snapshot_set_id" in res.data


def test_search_denies_snapshot_b_not_in_snapshot_set(monkeypatch):
    qsd = _import_query_server_dynamic(monkeypatch)

    class _Provider:
        def resolve(self, *, user_id, token, session_id, claims=None):
            return UserAccessContext(
                user_id=None,
                is_anonymous=True,
                group_ids=["developers"],
                allowed_pipelines=["rejewski"],
                allowed_commands=[],
                acl_tags_any=[],
            )

    class _Registry:
        def list_snapshots(self, *, snapshot_set_id, repository):
            class _S:
                def __init__(self, id):
                    self.id = id
            return [_S("allowed-1"), _S("allowed-2")]

    qsd._user_access_provider = _Provider()
    qsd._pipeline_snapshot_store = None
    qsd._snapshot_registry = _Registry()

    client = qsd.app.test_client()
    res = client.post(
        "/search",
        json={
            "pipelineName": "rejewski",
            "consultant": "rejewski",
            "query": "hi",
            "snapshot_set_id": "set1",
            "snapshots": ["allowed-1", "not-allowed-b"],
        },
        headers={"Authorization": "Bearer dev-user:john_kowalski"},
    )

    assert res.status_code == 400
    assert b"snapshot_id_b is not allowed in snapshot_set_id" in res.data
