from __future__ import annotations

import json
from pathlib import Path

from code_query_engine.llm_query_logger import log_llm_query


class _RespObj:
    def to_dict(self):
        return {"ok": True, "choices": [{"text": "hello"}]}


def test_llm_query_logger_disabled_does_not_write_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_QUERY_LOG", "0")
    monkeypatch.setenv("LLM_QUERY_LOG_DIR", str(tmp_path))

    log_llm_query(op="server_chat", request={"model": "x"}, response={"ok": True}, duration_ms=12)

    assert list(tmp_path.glob("llm_queries_*.jsonl")) == []


def test_llm_query_logger_enabled_writes_jsonl(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_QUERY_LOG", "1")
    monkeypatch.setenv("LLM_QUERY_LOG_DIR", str(tmp_path))

    cyclic = {"a": 1}
    cyclic["self"] = cyclic

    log_llm_query(
        op="server_chat",
        request={"payload": cyclic},
        response=_RespObj(),
        duration_ms=34,
    )

    files = sorted(tmp_path.glob("llm_queries_*.jsonl"))
    assert len(files) == 1

    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    row = json.loads(lines[0])
    assert row["op"] == "server_chat"
    assert row["duration_ms"] == 34
    assert row["request"]["payload"]["a"] == 1
    assert row["request"]["payload"]["self"] == "<recursion>"
    assert row["response"]["ok"] is True
    assert row["response"]["choices"][0]["text"] == "hello"
