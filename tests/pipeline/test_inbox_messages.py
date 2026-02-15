import os
from typing import Any, Dict, Optional

import pytest

from code_query_engine.pipeline.action_registry import ActionRegistry
from code_query_engine.pipeline.actions.base_action import PipelineActionBase
from code_query_engine.pipeline.definitions import PipelineDef, StepDef
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


class _DummyRuntime(PipelineRuntime):
    def __init__(self) -> None:
        super().__init__(
            pipeline_settings={},
            model=None,
            searcher=None,
            markdown_translator=None,
            translator_pl_en=None,
            history_manager=None,
            logger=None,
            constants=None,
            retrieval_backend=None,
            graph_provider=None,
            token_counter=None,
            add_plant_link=None,
        )


class _NoopAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "noop"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {}

    def log_out(
        self,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
        *,
        next_step_id: Optional[str],
        error: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {"next_step_id": next_step_id, "error": error}

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        return None


class _ProducerAction(_NoopAction):
    @property
    def action_id(self) -> str:
        return "producer"

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        state.enqueue_message(target_step_id="consumer", topic="test", payload={"a": 1})
        return None


class _ConsumerAction(_NoopAction):
    @property
    def action_id(self) -> str:
        return "consumer"

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # Base class populates this on step entry.
        msgs = list(getattr(state, "inbox_last_consumed", []) or [])
        state.answer_en = f"consumed={len(msgs)}"
        return None


def _state() -> PipelineState:
    return PipelineState(
        user_query="q",
        session_id="s",
        consultant="c",
        branch=None,
        translate_chat=False,
        snapshot_id="snap",
    )


def test_inbox_starts_empty():
    state = _state()
    assert state.inbox == []


def test_enqueue_appends_and_logs():
    state = _state()
    state.enqueue_message(target_step_id="x", topic="test", payload={"k": 1})
    assert len(state.inbox) == 1
    assert state.inbox[0]["target_step_id"] == "x"
    assert state.inbox[0]["topic"] == "test"

    events = list(getattr(state, "pipeline_trace_events", []) or [])
    assert any(e.get("event_type") == "ENQUEUE" for e in events)


def test_consume_by_step_id_logs_and_clears(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAG_PIPELINE_TRACE", "1")
    rt = _DummyRuntime()
    setattr(rt, "pipeline_trace_enabled", True)

    state = _state()
    state.enqueue_message(target_step_id="s1", topic="test", payload={"k": 1})
    state.enqueue_message(target_step_id="other", topic="test", payload={"k": 2})

    step = StepDef(id="s1", action="noop", raw={"next": None})
    _NoopAction().execute(step, state, rt)

    # Messages for s1 are consumed and cleared; others remain.
    assert all(m.get("target_step_id") != "s1" for m in state.inbox)
    assert any(m.get("target_step_id") == "other" for m in state.inbox)

    events = list(getattr(state, "pipeline_trace_events", []) or [])
    assert any(e.get("event_type") == "CONSUME" and e.get("consumer_step_id") == "s1" for e in events)
    # Also logged inside the action "in" section.
    step_events = [e for e in events if isinstance(e, dict) and "step" in e]
    assert step_events
    assert step_events[-1]["in"].get("_inbox_consume", {}).get("consumer_step_id") == "s1"


def test_other_step_does_not_consume(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAG_PIPELINE_TRACE", "1")
    rt = _DummyRuntime()
    setattr(rt, "pipeline_trace_enabled", True)

    state = _state()
    state.enqueue_message(target_step_id="other", topic="test", payload={"k": 2})

    step = StepDef(id="s1", action="noop", raw={"next": None})
    _NoopAction().execute(step, state, rt)

    assert len(state.inbox) == 1
    assert state.inbox[0]["target_step_id"] == "other"


def test_run_end_inbox_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAG_PIPELINE_TRACE", "1")
    monkeypatch.setenv("RAG_PIPELINE_INBOX_FAIL_FAST", "1")

    reg = ActionRegistry()
    reg.register("producer", _ProducerAction())
    reg.register("consumer", _ConsumerAction())

    pipe = PipelineDef(
        name="inbox",
        settings={"entry_step_id": "producer"},
        steps=[
            StepDef(id="producer", action="producer", raw={"next": "consumer"}),
            StepDef(id="consumer", action="consumer", raw={"end": True}),
        ],
    )

    state = _state()
    rt = _DummyRuntime()
    setattr(rt, "pipeline_trace_enabled", True)

    out = PipelineEngine(registry=reg).run(pipe, state, rt)
    assert out.final_answer == "consumed=1"

    events = list(getattr(state, "pipeline_trace_events", []) or [])
    run_end = [e for e in events if e.get("event_type") == "RUN_END"]
    assert run_end, "RUN_END trace event missing"
    assert run_end[-1]["inbox_remaining_count"] == 0


def test_run_end_inbox_fail_fast(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAG_PIPELINE_INBOX_FAIL_FAST", "1")

    reg = ActionRegistry()
    reg.register("producer", _ProducerAction())
    reg.register("noop", _NoopAction())

    pipe = PipelineDef(
        name="inbox",
        settings={"entry_step_id": "producer"},
        steps=[
            StepDef(id="producer", action="producer", raw={"next": "noop"}),
            StepDef(id="noop", action="noop", raw={"end": True}),
        ],
    )

    state = _state()
    rt = _DummyRuntime()

    with pytest.raises(RuntimeError, match="PIPELINE_INBOX_NOT_EMPTY"):
        PipelineEngine(registry=reg).run(pipe, state, rt)
