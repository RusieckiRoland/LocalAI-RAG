from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest


def _stub_module(monkeypatch: pytest.MonkeyPatch, module_name: str, attrs: dict[str, Any]) -> None:
    mod = types.ModuleType(module_name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    monkeypatch.setitem(sys.modules, module_name, mod)


def _install_common_import_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_module(monkeypatch, "common.markdown_translator_en_pl", {"MarkdownTranslator": lambda *a, **k: object()})
    _stub_module(monkeypatch, "common.translator_pl_en", {"TranslatorPlEn": lambda *a, **k: object(), "Translator": lambda *a, **k: object()})
    _stub_module(monkeypatch, "code_query_engine.model", {"Model": lambda *a, **k: object()})
    _stub_module(monkeypatch, "code_query_engine.log_utils", {"InteractionLogger": lambda *a, **k: object()})
    _stub_module(monkeypatch, "vector_db.weaviate_client", {"get_settings": lambda: {}, "create_client": lambda settings: None})

    class _DummyRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self, **kwargs: Any):
            return ("OK", "DIRECT", ["boot"], "stub")

    _stub_module(monkeypatch, "code_query_engine.dynamic_pipeline", {"DynamicPipelineRunner": _DummyRunner})


def _install_sqlalchemy_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    behavior_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    state: dict[str, Any] = {"create_engine_calls": [], "queries": []}

    class _Result:
        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar(self) -> Any:
            return self._value

    class _Connection:
        def __init__(self, *, behavior: dict[str, Any], url: str) -> None:
            self._behavior = behavior
            self._url = url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, stmt: Any) -> _Result:
            query = str(stmt)
            state["queries"].append({"url": self._url, "query": query})

            if self._behavior.get("fail_on_query"):
                raise RuntimeError(str(self._behavior.get("fail_message") or "query failed"))

            if "SELECT 1" in query:
                return _Result(1)

            if "to_regclass('chat_sessions')" in query:
                return _Result(self._behavior.get("chat_sessions_exists", True))
            if "to_regclass('security.groups')" in query:
                return _Result(self._behavior.get("groups_exists", True))
            if "to_regclass('security.configuration_versions')" in query:
                return _Result(self._behavior.get("configuration_versions_exists", True))

            return _Result(1)

    class _Engine:
        def __init__(self, *, url: str, behavior: dict[str, Any]) -> None:
            self._url = url
            self._behavior = behavior

        def connect(self) -> _Connection:
            if self._behavior.get("fail_on_connect"):
                raise RuntimeError(str(self._behavior.get("fail_message") or "connect failed"))
            return _Connection(behavior=self._behavior, url=self._url)

        def dispose(self) -> None:
            return None

    def create_engine(url: str, pool_pre_ping: bool = True, connect_args: dict[str, Any] | None = None):
        behavior = behavior_by_url.get(url, {})
        state["create_engine_calls"].append(
            {
                "url": url,
                "pool_pre_ping": pool_pre_ping,
                "connect_args": dict(connect_args or {}),
            }
        )
        return _Engine(url=url, behavior=behavior)

    sqlalchemy_mod = types.ModuleType("sqlalchemy")
    setattr(sqlalchemy_mod, "create_engine", create_engine)
    setattr(sqlalchemy_mod, "text", lambda q: q)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_mod)
    return state


def _import_server_with_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    runtime_cfg: dict[str, Any],
    app_profile: str,
):
    config_path = tmp_path / "runtime_config.json"
    config_path.write_text(json.dumps(runtime_cfg), encoding="utf-8")

    monkeypatch.setenv("APP_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("APP_PROFILE", app_profile)
    monkeypatch.setenv("APP_USE_REDIS", "false")
    monkeypatch.setenv("IDP_AUTH_ENABLED", "0")
    monkeypatch.setenv("WEAVIATE_SKIP_INIT", "1")
    monkeypatch.setenv("API_TOKEN", "")

    _install_common_import_stubs(monkeypatch)
    sys.modules.pop("code_query_engine.query_server_dynamic", None)
    return importlib.import_module("code_query_engine.query_server_dynamic")


def test_dev_without_sql_config_uses_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    qsd = _import_server_with_config(
        monkeypatch,
        tmp_path=tmp_path,
        app_profile="dev",
        runtime_cfg={"development": True, "mockSqlServer": True},
    )

    assert qsd._sql_enabled is False


def test_dev_sql_enabled_requires_connection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_sqlalchemy_stub(
        monkeypatch,
        behavior_by_url={
            "postgresql://history-db": {"fail_on_connect": True, "fail_message": "history down"},
            "postgresql://security-db": {},
        },
    )

    with pytest.raises(RuntimeError, match=r"history down"):
        _import_server_with_config(
            monkeypatch,
            tmp_path=tmp_path,
            app_profile="dev",
            runtime_cfg={
                "development": True,
                "sql": {
                    "enabled": True,
                    "database_type": "postgres",
                    "history": {"connection_url": "postgresql://history-db"},
                    "security": {"connection_url": "postgresql://security-db"},
                },
            },
        )


def test_sql_env_placeholders_are_expanded_and_validated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HISTORY_DB_URL", "postgresql://history-db")
    monkeypatch.setenv("SECURITY_DB_URL", "postgresql://security-db")
    sa_state = _install_sqlalchemy_stub(
        monkeypatch,
        behavior_by_url={
            "postgresql://history-db": {"chat_sessions_exists": True},
            "postgresql://security-db": {"groups_exists": True, "configuration_versions_exists": True},
        },
    )

    qsd = _import_server_with_config(
        monkeypatch,
        tmp_path=tmp_path,
        app_profile="dev",
        runtime_cfg={
            "development": True,
            "sql": {
                "enabled": True,
                "database_type": "postgres",
                "connect_timeout_seconds": 11,
                "history": {"connection_url": "${HISTORY_DB_URL}"},
                "security": {"connection_url": "${SECURITY_DB_URL}"},
            },
        },
    )

    assert qsd._sql_enabled is True
    assert qsd._sql_runtime["history_url"] == "postgresql://history-db"
    assert qsd._sql_runtime["security_url"] == "postgresql://security-db"
    assert [c["url"] for c in sa_state["create_engine_calls"]] == ["postgresql://history-db", "postgresql://security-db"]
    assert all(c["connect_args"] == {"connect_timeout": 11} for c in sa_state["create_engine_calls"])


def test_prod_requires_sql_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"APP_PROFILE=prod requires SQL configuration"):
        _import_server_with_config(
            monkeypatch,
            tmp_path=tmp_path,
            app_profile="prod",
            runtime_cfg={"development": False},
        )


def test_prod_requires_database_type_when_sql_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"sql\.database_type is required"):
        _import_server_with_config(
            monkeypatch,
            tmp_path=tmp_path,
            app_profile="prod",
            runtime_cfg={
                "development": False,
                "sql": {
                    "enabled": True,
                    "history": {"connection_url": "postgresql://history-db"},
                    "security": {"connection_url": "postgresql://security-db"},
                },
            },
        )
