from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("path", "table_token", "seed_token"),
    [
        (
            "docs/sqldb/security_schema_postgres.sql",
            "CREATE TABLE IF NOT EXISTS security.configuration_versions",
            "INSERT INTO security.configuration_versions",
        ),
        (
            "docs/sqldb/security_schema_mssql.sql",
            "CREATE TABLE security.configuration_versions",
            "INSERT INTO security.configuration_versions",
        ),
        (
            "docs/sqldb/security_schema_mysql.sql",
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
