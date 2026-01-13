import pytest

from code_query_engine.pipeline.actions.set_variables import SetVariablesAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class DummyRuntime:
    pipeline_settings = {}


def _mk_state() -> PipelineState:
    return PipelineState(
        user_query="q",
        session_id="s",
        consultant="c",
        branch="b",
        translate_chat=False,
    )


def test_set_variables_copy_value() -> None:
    a = SetVariablesAction()
    s = _mk_state()

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "retrieval_mode", "value": "semantic"},
            ],
        },
    )

    a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]
    assert s.retrieval_mode == "semantic"


def test_set_variables_from_missing_attr_is_error() -> None:
    a = SetVariablesAction()
    s = _mk_state()

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "retrieval_mode", "from": "does_not_exist"},
            ],
        },
    )

    with pytest.raises(ValueError, match=r"source field not found on state"):
        a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]


def test_set_variables_from_and_value_conflict_is_error() -> None:
    a = SetVariablesAction()
    s = _mk_state()

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "retrieval_mode", "from": "user_query", "value": "x"},
            ],
        },
    )

    with pytest.raises(ValueError, match=r"must provide exactly one of 'from' or 'value'"):
        a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]


def test_set_variables_dot_path_is_error() -> None:
    a = SetVariablesAction()
    s = _mk_state()

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "a.b", "value": 1},
            ],
        },
    )

    with pytest.raises(ValueError, match=r"'set' must not contain '\.'"):
        a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]


def test_transform_to_list_none() -> None:
    a = SetVariablesAction()
    s = _mk_state()
    s.router_raw = None

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "context_blocks", "from": "router_raw", "transform": "to_list"},
            ],
        },
    )

    a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]
    assert s.context_blocks == []


def test_transform_split_lines() -> None:
    a = SetVariablesAction()
    s = _mk_state()
    s.router_raw = "a\n\n b\r\n"

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "context_blocks", "from": "router_raw", "transform": "split_lines"},
            ],
        },
    )

    a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]
    assert s.context_blocks == ["a", "b"]


def test_transform_parse_json_ok() -> None:
    a = SetVariablesAction()
    s = _mk_state()
    s.router_raw = '{"a":1}'

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "retrieval_filters", "from": "router_raw", "transform": "parse_json"},
            ],
        },
    )

    a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]
    assert s.retrieval_filters == {"a": 1}


def test_transform_to_context_blocks_from_string() -> None:
    a = SetVariablesAction()
    s = _mk_state()
    s.router_raw = " hello "

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "context_blocks", "from": "router_raw", "transform": "to_context_blocks"},
            ],
        },
    )

    a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]
    assert s.context_blocks == [" hello "]


def test_transform_to_context_blocks_from_list_of_dicts_strict() -> None:
    a = SetVariablesAction()
    s = _mk_state()
    s.retrieval_filters = {}  # just a placeholder field; we overwrite context_blocks

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "context_blocks", "value": [{"text": "a"}, {"text": "  "}, {"text": "b"}], "transform": "to_context_blocks"},
            ],
        },
    )

    a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]
    assert s.context_blocks == ["a", "b"]


def test_transform_to_context_blocks_missing_text_is_error() -> None:
    a = SetVariablesAction()
    s = _mk_state()

    step = StepDef(
        id="x",
        action="set_variables",
        raw={
            "id": "x",
            "action": "set_variables",
            "rules": [
                {"set": "context_blocks", "value": [{"nope": "x"}], "transform": "to_context_blocks"},
            ],
        },
    )

    with pytest.raises(ValueError, match=r"invalid context block"):
        a.do_execute(step, s, DummyRuntime())  # type: ignore[arg-type]
