import importlib
import sys
import types

from server.auth.user_access import UserAccessContext


def _import_query_server_dynamic(monkeypatch):
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
        def resolve(self, *, user_id, token, session_id):
            return UserAccessContext(
                user_id=None,
                is_anonymous=True,
                group_ids=["anonymous"],
                allowed_pipelines=["ada"],
                allowed_commands=[],
                acl_tags_all=[],
            )

    qsd._user_access_provider = _Provider()
    qsd._pipeline_snapshot_store = None
    qsd._snapshot_registry = None

    client = qsd.app.test_client()
    res = client.post("/search", json={"consultant": "rejewski", "query": "hi"})

    assert res.status_code == 403


def test_search_returns_400_for_unknown_snapshot_set(monkeypatch):
    qsd = _import_query_server_dynamic(monkeypatch)

    class _Provider:
        def resolve(self, *, user_id, token, session_id):
            return UserAccessContext(
                user_id=None,
                is_anonymous=True,
                group_ids=["authenticated"],
                allowed_pipelines=["rejewski"],
                allowed_commands=[],
                acl_tags_all=[],
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
    res = client.post("/search", json={"pipelineName": "rejewski", "consultant": "rejewski", "query": "hi"})

    assert res.status_code == 400
    assert b"unknown snapshot_set_id" in res.data
