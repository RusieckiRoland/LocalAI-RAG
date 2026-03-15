from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("path", "table_token", "seed_token"),
    [
        (
            "docs/sqldb/history_security_schema_postgres.sql",
            "CREATE TABLE IF NOT EXISTS security.configuration_versions",
            "INSERT INTO security.configuration_versions",
        ),
        (
            "docs/sqldb/history_security_schema_mssql.sql",
            "CREATE TABLE security.configuration_versions",
            "INSERT INTO security.configuration_versions",
        ),
        (
            "docs/sqldb/history_security_schema_mysql.sql",
            "CREATE TABLE IF NOT EXISTS security_configuration_versions",
            "INSERT INTO security_configuration_versions",
        ),
    ],
)
def test_security_schema_contains_configuration_versions_table_and_seed(path: str, table_token: str, seed_token: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    assert table_token in text
    assert seed_token in text
    assert "config_source" in text
    assert "valid_from" in text
    assert "valid_to" in text
    assert "'json'" in text or "N'json'" in text


@pytest.mark.parametrize(
    ("path", "history_token", "security_token"),
    [
        (
            "docs/sqldb/history_security_schema_postgres.sql",
            "CREATE SCHEMA IF NOT EXISTS history",
            "CREATE SCHEMA IF NOT EXISTS security",
        ),
        (
            "docs/sqldb/history_security_schema_mssql.sql",
            "CREATE SCHEMA history AUTHORIZATION dbo",
            "CREATE SCHEMA security AUTHORIZATION dbo",
        ),
        (
            "docs/sqldb/history_security_schema_mysql.sql",
            "CREATE DATABASE IF NOT EXISTS localai_rag_history",
            "CREATE DATABASE IF NOT EXISTS localai_rag_security",
        ),
    ],
)
def test_combined_schema_documents_cover_history_and_security(path: str, history_token: str, security_token: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    assert history_token in text
    assert security_token in text
    assert "chat_sessions" in text
    assert "configuration_versions" in text
