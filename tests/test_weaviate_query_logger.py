from __future__ import annotations

import json
from pathlib import Path

from code_query_engine.weaviate_query_logger import log_weaviate_query


class _FilterLike:
    __module__ = "weaviate.classes.filters"

    def __init__(self) -> None:
        self.operator = "And"
        self.operands = ["x", "y"]



def test_weaviate_query_logger_disabled_does_not_write_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEAVIATE_QUERY_LOG", "0")
    monkeypatch.setenv("WEAVIATE_QUERY_LOG_DIR", str(tmp_path))

    log_weaviate_query(op="search", request={"q": "cat"}, response={"hits": 1}, duration_ms=11)

    assert list(tmp_path.glob("weaviate_queries_*.jsonl")) == []



def test_weaviate_query_logger_enabled_writes_preview(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEAVIATE_QUERY_LOG", "1")
    monkeypatch.setenv("WEAVIATE_QUERY_LOG_DIR", str(tmp_path))

    log_weaviate_query(
        op="search",
        request={"where": _FilterLike(), "query": "class Category"},
        response={"objects": [{"id": "N1", "text": "A" * 400}]},
        duration_ms=29,
    )

    files = sorted(tmp_path.glob("weaviate_queries_*.jsonl"))
    assert len(files) == 1

    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    row = json.loads(lines[0])
    assert row["op"] == "search"
    assert row["duration_ms"] == 29
    assert "query" in row["request"]
    assert "response_preview" in row
    assert isinstance(row["response_preview"], str)
    assert len(row["response_preview"]) <= 200
