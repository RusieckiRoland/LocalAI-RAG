from __future__ import annotations

from dataclasses import dataclass

import pytest

from code_query_engine.llm_server_client import ServerLLMClient, ServerLLMConfig


@dataclass
class _State:
    llm_server_security_override_notice: str | None = None


def _client_with_servers(servers: dict[str, ServerLLMConfig], default_name: str) -> ServerLLMClient:
    ordered = list(servers.keys())
    return ServerLLMClient(servers=servers, default_name=default_name, ordered_names=ordered)


def test_acl_trust_ignored_when_acl_list_present() -> None:
    server = ServerLLMConfig(
        name="s1",
        base_url="http://example",
        allowed_acl_labels=("internal",),
        is_trusted_for_all_acl=True,
    )
    client = _client_with_servers({"s1": server}, default_name="s1")
    ok = client._server_allows_security(
        server,
        {
            "acl_labels_union": ["restricted"],
            "classification_labels_union": [],
            "doc_level_max": None,
        },
    )
    assert ok is False


def test_acl_trust_all_applies_when_acl_list_empty() -> None:
    server = ServerLLMConfig(
        name="s1",
        base_url="http://example",
        allowed_acl_labels=(),
        is_trusted_for_all_acl=True,
    )
    client = _client_with_servers({"s1": server}, default_name="s1")
    ok = client._server_allows_security(
        server,
        {
            "acl_labels_union": ["restricted", "internal"],
            "classification_labels_union": [],
            "doc_level_max": None,
        },
    )
    assert ok is True


def test_doc_level_max_enforced() -> None:
    server = ServerLLMConfig(
        name="s1",
        base_url="http://example",
        allowed_doc_level=2,
    )
    client = _client_with_servers({"s1": server}, default_name="s1")
    ok = client._server_allows_security(
        server,
        {
            "doc_level_max": 3,
            "acl_labels_union": [],
            "classification_labels_union": [],
        },
    )
    assert ok is False


def test_classification_labels_subset_required() -> None:
    server = ServerLLMConfig(
        name="s1",
        base_url="http://example",
        allowed_classification_labels=("public",),
    )
    client = _client_with_servers({"s1": server}, default_name="s1")
    ok = client._server_allows_security(
        server,
        {
            "doc_level_max": None,
            "acl_labels_union": [],
            "classification_labels_union": ["restricted"],
        },
    )
    assert ok is False


def test_trusted_server_skips_checks() -> None:
    server = ServerLLMConfig(
        name="s1",
        base_url="http://example",
        allowed_doc_level=None,
        allowed_acl_labels=(),
        allowed_classification_labels=(),
        is_trusted_server=True,
    )
    client = _client_with_servers({"s1": server}, default_name="s1")
    ok = client._server_allows_security(
        server,
        {
            "doc_level_max": 999,
            "acl_labels_union": ["restricted"],
            "classification_labels_union": ["secret"],
        },
    )
    assert ok is True


def test_override_notice_set_when_fallback_server_used() -> None:
    primary = ServerLLMConfig(
        name="primary",
        base_url="http://example",
        allowed_acl_labels=("public",),
    )
    secondary = ServerLLMConfig(
        name="secondary",
        base_url="http://example2",
        allowed_acl_labels=("public", "restricted"),
    )
    client = _client_with_servers({"primary": primary, "secondary": secondary}, default_name="primary")
    state = _State()
    security_context = {
        "doc_level_max": None,
        "acl_labels_union": ["restricted"],
        "classification_labels_union": [],
        "translate_chat": False,
        "state": state,
        "pipeline_settings": {
            "llm_server_security_messages_default": {
                "override_notice": {
                    "neutral": "override-neutral",
                    "translated": "override-translated",
                },
                "no_server_notice": {
                    "neutral": "no-server-neutral",
                    "translated": "no-server-translated",
                },
            }
        },
    }
    server, notice_kind = client._select_server(None, security_context=security_context)
    assert server is not None
    assert server.name == "secondary"
    assert notice_kind == "override"
    client._apply_security_notice(security_context, notice_kind)
    assert state.llm_server_security_override_notice == "override-neutral"


def test_no_server_notice_when_none_match() -> None:
    primary = ServerLLMConfig(
        name="primary",
        base_url="http://example",
        allowed_acl_labels=("public",),
    )
    client = _client_with_servers({"primary": primary}, default_name="primary")
    state = _State()
    security_context = {
        "doc_level_max": None,
        "acl_labels_union": ["restricted"],
        "classification_labels_union": [],
        "translate_chat": True,
        "state": state,
        "pipeline_settings": {
            "llm_server_security_messages_default": {
                "override_notice": {
                    "neutral": "override-neutral",
                    "translated": "override-translated",
                },
                "no_server_notice": {
                    "neutral": "no-server-neutral",
                    "translated": "no-server-translated",
                },
            }
        },
    }
    server, notice_kind = client._select_server(None, security_context=security_context)
    assert server is None
    assert notice_kind == "no_server"
    client._apply_security_notice(security_context, notice_kind)
    assert state.llm_server_security_override_notice == "no-server-translated"
