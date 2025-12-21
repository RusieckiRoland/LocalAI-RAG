from __future__ import annotations

import json
from pathlib import Path

from code_query_engine.pipeline.providers.file_system_graph_provider import FileSystemGraphProvider


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_filesystem_graph_provider_fetch_node_texts_returns_code_and_sql_texts(tmp_path: Path) -> None:
    repo = "r"
    branch = "b"
    root = tmp_path / "repositories" / repo / "branches" / branch

    # regular_code_bundle/chunks.json
    chunks_path = root / "regular_code_bundle" / "chunks.json"
    _write_text(
        chunks_path,
        json.dumps(
            [
                {"Id": "A", "File": "src/a.cs", "Text": "class A {}"},
                {"Id": "B", "File": "src/b.cs", "Text": "class B {}"},
            ],
            ensure_ascii=False,
        ),
    )

    # regular_code_bundle/dependencies.json (not required for fetch, but common layout)
    deps_path = root / "regular_code_bundle" / "dependencies.json"
    _write_text(deps_path, json.dumps({"A": ["B"]}, ensure_ascii=False))

    # sql_bundle/docs/sql_bodies.jsonl
    sql_path = root / "sql_bundle" / "docs" / "sql_bodies.jsonl"
    _write_text(
        sql_path,
        "\n".join(
            [
                json.dumps(
                    {
                        "key": "S1",
                        "kind": "Proc",
                        "schema": "dbo",
                        "name": "P1",
                        "file": "sql/p1.sql",
                        "body": "SELECT 1;",
                    },
                    ensure_ascii=False,
                )
            ]
        )
        + "\n",
    )

    gp = FileSystemGraphProvider(repositories_root=str(tmp_path / "repositories"))

    out = gp.fetch_node_texts(
        node_ids=["A", "S1", "UNKNOWN"],
        repository=repo,
        branch=branch,
        active_index=None,
        max_chars=50_000,
    )

    # Expect contract A: [{"id": ..., "text": ...}, ...]
    assert [x["id"] for x in out] == ["A", "S1", "UNKNOWN"]

    a = out[0]["text"]
    assert "### File: src/a.cs" in a
    assert "class A" in a

    s1 = out[1]["text"]
    assert "[SQL Proc] dbo.P1" in s1
    assert "SELECT 1" in s1

    unk = out[2]["text"]
    assert unk == ""
