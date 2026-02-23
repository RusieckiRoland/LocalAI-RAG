from typing import Optional

import pytest

from classifiers.code_classifier import CodeKind
from code_query_engine.pipeline.actions.manage_context_budget import ManageContextBudgetAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


class _TokenCounter:
    # Deterministic and simple: 1 token per word.
    def count_tokens(self, text: str) -> int:
        return len([w for w in str(text or "").split() if w])

    def count(self, text: str) -> int:
        return self.count_tokens(text)


def _rt(*, max_context_tokens: int) -> PipelineRuntime:
    rt = PipelineRuntime(
        pipeline_settings={"max_context_tokens": max_context_tokens},
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=None,
        constants=None,
        retrieval_backend=None,
        graph_provider=None,
        token_counter=_TokenCounter(),
        add_plant_link=None,
    )
    setattr(rt, "pipeline_trace_enabled", True)
    return rt


def _state(*, node_texts: list[dict], context_blocks: Optional[list[str]] = None) -> PipelineState:
    s = PipelineState(
        user_query="q",
        session_id="s",
        consultant="c",
        branch=None,
        translate_chat=False,
        snapshot_id="snap",
    )
    s.node_texts = list(node_texts)
    s.context_blocks = list(context_blocks or [])
    return s


def _step(raw: dict) -> StepDef:
    return StepDef(id="manage_budget", action="manage_context_budget", raw=raw)


@pytest.fixture(autouse=True)
def _trace_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAG_PIPELINE_TRACE", "1")
    yield


def test_always_sql_calls_tsql_summarizer(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def _fake_summarize(sql: str) -> dict:
        calls.append("summarize")
        return {"object": "dbo.x"}

    def _fake_make_compact(payload: dict, **_kw):
        calls.append("make_compact")
        return {"obj": payload.get("object")}

    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )
    monkeypatch.setattr("tsql_summarizer.api.summarize_tsql", _fake_summarize)
    monkeypatch.setattr("tsql_summarizer.api.make_compact", _fake_make_compact)

    rt = _rt(max_context_tokens=200)
    state = _state(node_texts=[{"node_id": "n1", "text": "select 1"}])
    step = _step(
        {
            "compact_code": {"rules": [{"language": "sql", "policy": "always"}]},
            "on_ok": "ok",
            "on_over": "over",
        }
    )

    nxt = ManageContextBudgetAction().execute(step, state, rt)
    assert nxt == "ok"
    assert calls == ["summarize", "make_compact"]


def test_threshold_policy_compacts_only_above_threshold(monkeypatch: pytest.MonkeyPatch):
    # Force language=sql
    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )

    compact_calls: list[str] = []

    def _fake_summarize(sql: str) -> dict:
        compact_calls.append("summarize")
        return {"object": "dbo.x"}

    def _fake_make_compact(payload: dict, **_kw):
        compact_calls.append("make_compact")
        return {"obj": payload.get("object")}

    monkeypatch.setattr("tsql_summarizer.api.summarize_tsql", _fake_summarize)
    monkeypatch.setattr("tsql_summarizer.api.make_compact", _fake_make_compact)

    rt = _rt(max_context_tokens=200)

    # High threshold => no compaction expected
    state = _state(node_texts=[{"node_id": "n1", "text": "select 1"}], context_blocks=["x " * 10])
    step = _step(
        {
            "compact_code": {"rules": [{"language": "sql", "policy": "threshold", "threshold": 0.9}]},
            "on_ok": "ok",
            "on_over": "over",
        }
    )
    nxt = ManageContextBudgetAction().execute(step, state, rt)
    assert nxt == "ok"
    assert compact_calls == []

    # Low threshold => compaction expected
    compact_calls.clear()
    # threshold=0.1 => 20 tokens; make current context close to threshold so adding the node crosses it.
    state2 = _state(node_texts=[{"node_id": "n2", "text": "select 1"}], context_blocks=["x " * 19])
    step2 = _step(
        {
            "compact_code": {"rules": [{"language": "sql", "policy": "threshold", "threshold": 0.1}]},
            "on_ok": "ok",
            "on_over": "over",
        }
    )
    nxt2 = ManageContextBudgetAction().execute(step2, state2, rt)
    assert nxt2 == "ok"
    assert compact_calls == ["summarize", "make_compact"]


def test_demand_policy_no_inbox_no_compaction(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )

    calls: list[str] = []

    def _fake_summarize(sql: str) -> dict:
        calls.append("summarize")
        return {}

    monkeypatch.setattr("tsql_summarizer.api.summarize_tsql", _fake_summarize)

    rt = _rt(max_context_tokens=200)
    state = _state(node_texts=[{"node_id": "n1", "text": "select 1"}])
    step = _step(
        {
            "compact_code": {"rules": [{"language": "sql", "policy": "demand", "inbox_key": "compact_sql"}]},
            "on_ok": "ok",
            "on_over": "over",
        }
    )

    nxt = ManageContextBudgetAction().execute(step, state, rt)
    assert nxt == "ok"
    assert calls == []


def test_demand_policy_inbox_compacts_and_consumes_on_ok(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )

    calls: list[str] = []

    def _fake_summarize(sql: str) -> dict:
        calls.append("summarize")
        return {}

    def _fake_make_compact(payload: dict, **_kw):
        calls.append("make_compact")
        return {"x": 1}

    monkeypatch.setattr("tsql_summarizer.api.summarize_tsql", _fake_summarize)
    monkeypatch.setattr("tsql_summarizer.api.make_compact", _fake_make_compact)

    rt = _rt(max_context_tokens=200)
    state = _state(node_texts=[{"node_id": "n1", "text": "select 1"}])
    # Enqueue demand request addressed to this step id.
    state.enqueue_message(target_step_id="manage_budget", topic="compact_sql", payload={"why": "test"})

    step = _step(
        {
            "compact_code": {"rules": [{"language": "sql", "policy": "demand", "inbox_key": "compact_sql"}]},
            "on_ok": "ok",
            "on_over": "over",
        }
    )

    nxt = ManageContextBudgetAction().execute(step, state, rt)
    assert nxt == "ok"
    assert calls == ["summarize", "make_compact"]
    assert state.node_texts == []
    # Demand message was consumed on entry and not re-enqueued on ok.
    assert state.inbox == []


def test_on_over_leaves_node_texts_and_reenqueues_demand(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )

    def _fake_summarize(sql: str) -> dict:
        return {}

    def _fake_make_compact(payload: dict, **_kw):
        return {"x": 1}

    monkeypatch.setattr("tsql_summarizer.api.summarize_tsql", _fake_summarize)
    monkeypatch.setattr("tsql_summarizer.api.make_compact", _fake_make_compact)

    # Current context already consumes almost all budget; any addition triggers on_over.
    rt = _rt(max_context_tokens=30)
    state = _state(
        node_texts=[{"node_id": "n1", "text": "select 1"}],
        context_blocks=["x " * 30],
    )
    state.enqueue_message(target_step_id="manage_budget", topic="compact_sql", payload={"why": "test"})

    step = _step(
        {
            "compact_code": {"rules": [{"language": "sql", "policy": "demand", "inbox_key": "compact_sql"}]},
            "on_ok": "ok",
            "on_over": "over",
        }
    )

    nxt = ManageContextBudgetAction().execute(step, state, rt)
    assert nxt == "over"
    assert state.node_texts != []
    # Demand was re-enqueued to persist for retry.
    assert any(m.get("topic") == "compact_sql" and m.get("target_step_id") == "manage_budget" for m in state.inbox)


def test_misconfig_raises_when_incoming_alone_cannot_fit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )

    monkeypatch.setattr("tsql_summarizer.api.summarize_tsql", lambda _sql: {})
    monkeypatch.setattr("tsql_summarizer.api.make_compact", lambda _p, **_kw: {"x": 1})

    rt = _rt(max_context_tokens=5)
    # Incoming is huge relative to budget.
    state = _state(node_texts=[{"node_id": "n1", "text": "select " + ("x " * 200)}])
    step = _step({"on_ok": "ok", "on_over": "over"})

    with pytest.raises(RuntimeError) as ex:
        ManageContextBudgetAction().execute(step, state, rt)
    assert "PIPELINE_BUDGET_MISCONFIG" in str(ex.value)


def test_divide_new_content_marks_only_fresh_blocks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )

    rt = _rt(max_context_tokens=300)
    state = _state(
        node_texts=[{"node_id": "n1", "text": "select 1"}],
        context_blocks=["<<<New content\nOLD BLOCK"],
    )
    step = _step(
        {
            "divide_new_content": "<<<New content",
            "on_ok": "ok",
            "on_over": "over",
        }
    )

    nxt = ManageContextBudgetAction().execute(step, state, rt)
    assert nxt == "ok"
    assert state.node_texts == []
    assert len(state.context_blocks) == 2
    assert state.context_blocks[0] == "OLD BLOCK"
    assert state.context_blocks[1].startswith("<<<New content\n--- NODE ---")


def test_divide_new_content_old_marker_removed_without_new_append(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "code_query_engine.pipeline.actions.manage_context_budget.classify_text",
        lambda _t: type("R", (), {"kind": CodeKind.SQL})(),
    )

    rt = _rt(max_context_tokens=300)
    state = _state(
        node_texts=[],
        context_blocks=["<<<New content\nOLD BLOCK"],
    )
    step = _step(
        {
            "divide_new_content": "<<<New content",
            "on_ok": "ok",
            "on_over": "over",
        }
    )

    nxt = ManageContextBudgetAction().execute(step, state, rt)
    assert nxt == "ok"
    assert state.context_blocks == ["OLD BLOCK"]
