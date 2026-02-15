from __future__ import annotations

import json

import pytest

from code_query_engine.pipeline.actions.repeat_query_guard import RepeatQueryGuardAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


def _runtime() -> PipelineRuntime:
    return PipelineRuntime(
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


def _state_with_payload(payload: dict | str) -> PipelineState:
    s = PipelineState(
        user_query="q",
        session_id="s",
        consultant="c",
        translate_chat=False,
        snapshot_id="snap",
    )
    if isinstance(payload, str):
        s.last_model_response = payload
    else:
        s.last_model_response = json.dumps(payload)
    return s


def test_repeat_query_guard_routes_on_ok_for_new_query() -> None:
    step = StepDef(
        id="guard",
        action="repeat_query_guard",
        raw={
            "id": "guard",
            "action": "repeat_query_guard",
            "query_parser": "jsonish_v1",
            "on_ok": "search",
            "on_repeat": "loop",
        },
    )

    state = _state_with_payload({"query": "class Foo"})
    state.retrieval_queries_asked_norm = {"class bar"}

    nxt = RepeatQueryGuardAction().execute(step, state, _runtime())
    assert nxt == "search"


def test_repeat_query_guard_routes_on_repeat_for_empty_or_duplicate() -> None:
    step = StepDef(
        id="guard",
        action="repeat_query_guard",
        raw={
            "id": "guard",
            "action": "repeat_query_guard",
            "query_parser": "jsonish_v1",
            "on_ok": "search",
            "on_repeat": "loop",
        },
    )

    state_empty = _state_with_payload({"query": "  "})
    assert RepeatQueryGuardAction().execute(step, state_empty, _runtime()) == "loop"

    state_dup = _state_with_payload({"query": "Class Foo"})
    state_dup.retrieval_queries_asked_norm = {"class foo"}
    assert RepeatQueryGuardAction().execute(step, state_dup, _runtime()) == "loop"


def test_repeat_query_guard_no_parser_treats_payload_as_query() -> None:
    step = StepDef(
        id="guard",
        action="repeat_query_guard",
        raw={
            "id": "guard",
            "action": "repeat_query_guard",
            "on_ok": "search",
            "on_repeat": "loop",
        },
    )

    state = _state_with_payload("  raw query  ")
    nxt = RepeatQueryGuardAction().execute(step, state, _runtime())
    assert nxt == "search"


def test_repeat_query_guard_parser_name_alias_matches_jsonish() -> None:
    step = StepDef(
        id="guard",
        action="repeat_query_guard",
        raw={
            "id": "guard",
            "action": "repeat_query_guard",
            "query_parser": "JsonishQueryParser",
            "on_ok": "search",
            "on_repeat": "loop",
        },
    )

    state = _state_with_payload({"query": "class Foo"})
    nxt = RepeatQueryGuardAction().execute(step, state, _runtime())
    assert nxt == "search"


def test_repeat_query_guard_requires_routes_and_parser_name() -> None:
    state = _state_with_payload({"query": "x"})

    step_missing_ok = StepDef(
        id="guard",
        action="repeat_query_guard",
        raw={"id": "guard", "action": "repeat_query_guard", "on_repeat": "loop"},
    )
    with pytest.raises(ValueError, match="on_ok is required"):
        RepeatQueryGuardAction().execute(step_missing_ok, state, _runtime())

    step_missing_repeat = StepDef(
        id="guard",
        action="repeat_query_guard",
        raw={"id": "guard", "action": "repeat_query_guard", "on_ok": "search"},
    )
    with pytest.raises(ValueError, match="on_repeat is required"):
        RepeatQueryGuardAction().execute(step_missing_repeat, state, _runtime())

    step_unknown_parser = StepDef(
        id="guard",
        action="repeat_query_guard",
        raw={
            "id": "guard",
            "action": "repeat_query_guard",
            "query_parser": "unknown",
            "on_ok": "search",
            "on_repeat": "loop",
        },
    )
    with pytest.raises(ValueError, match="Unknown query_parser"):
        RepeatQueryGuardAction().execute(step_unknown_parser, state, _runtime())
