from __future__ import annotations

import json

import pytest

from code_query_engine.pipeline.actions.json_decision_router import JsonDecisionRouterAction
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


def test_json_decision_router_routes_and_cleans_payload() -> None:
    step = StepDef(
        id="route",
        action="json_decision_router",
        raw={
            "id": "route",
            "action": "json_decision_router",
            "routes": {"direct": "direct_step", "retrieve": "search_step"},
            "on_other": "fallback",
        },
    )

    state = _state_with_payload(
        {
            "decision": "retrieve",
            "query": "class Foo",
            "filters": {"data_type": "regular_code"},
        }
    )

    nxt = JsonDecisionRouterAction().execute(step, state, _runtime())

    assert nxt == "search_step"
    # decision keys must be removed
    assert json.loads(state.last_model_response) == {"filters": {"data_type": "regular_code"}, "query": "class Foo"}


def test_json_decision_router_on_other_for_unknown_decision() -> None:
    step = StepDef(
        id="route",
        action="json_decision_router",
        raw={
            "id": "route",
            "action": "json_decision_router",
            "routes": {"direct": "direct_step"},
            "on_other": "fallback",
        },
    )

    state = _state_with_payload({"decision": "unknown"})
    nxt = JsonDecisionRouterAction().execute(step, state, _runtime())
    assert nxt == "fallback"


def test_json_decision_router_on_other_for_non_object_payload() -> None:
    step = StepDef(
        id="route",
        action="json_decision_router",
        raw={
            "id": "route",
            "action": "json_decision_router",
            "routes": {"direct": "direct_step"},
            "on_other": "fallback",
        },
    )

    state = _state_with_payload("not a json object")
    nxt = JsonDecisionRouterAction().execute(step, state, _runtime())
    assert nxt == "fallback"


def test_json_decision_router_requires_routes_and_on_other() -> None:
    state = _state_with_payload({"decision": "direct"})

    step_missing_routes = StepDef(
        id="route",
        action="json_decision_router",
        raw={"id": "route", "action": "json_decision_router", "on_other": "x"},
    )
    with pytest.raises(ValueError, match="routes must be a non-empty dict"):
        JsonDecisionRouterAction().execute(step_missing_routes, state, _runtime())

    step_missing_on_other = StepDef(
        id="route",
        action="json_decision_router",
        raw={"id": "route", "action": "json_decision_router", "routes": {"direct": "x"}},
    )
    with pytest.raises(ValueError, match="on_other is required"):
        JsonDecisionRouterAction().execute(step_missing_on_other, state, _runtime())


def test_json_decision_router_supports_route_alias_and_jsonish() -> None:
    step = StepDef(
        id="route",
        action="json_decision_router",
        raw={
            "id": "route",
            "action": "json_decision_router",
            "routes": {"retrieve": "search_step"},
            "on_other": "fallback",
        },
    )

    payload = """```json
{route:\"retrieve\",query:\"class Foo\",filters:{data_type:\"regular_code\",},}
```"""

    state = _state_with_payload(payload)

    nxt = JsonDecisionRouterAction().execute(step, state, _runtime())

    assert nxt == "search_step"
    assert json.loads(state.last_model_response) == {"filters": {"data_type": "regular_code"}, "query": "class Foo"}


def test_json_decision_router_supports_mode_alias() -> None:
    step = StepDef(
        id="route",
        action="json_decision_router",
        raw={
            "id": "route",
            "action": "json_decision_router",
            "routes": {"direct": "direct_step"},
            "on_other": "fallback",
        },
    )

    state = _state_with_payload({"mode": "direct", "query": "class Foo"})
    nxt = JsonDecisionRouterAction().execute(step, state, _runtime())

    assert nxt == "direct_step"
    assert json.loads(state.last_model_response) == {"query": "class Foo"}


def test_json_decision_router_missing_decision_routes_to_on_other_and_cleans() -> None:
    step = StepDef(
        id="route",
        action="json_decision_router",
        raw={
            "id": "route",
            "action": "json_decision_router",
            "routes": {"direct": "direct_step"},
            "on_other": "fallback",
        },
    )

    state = _state_with_payload({"query": "class Foo", "filters": {"data_type": "regular_code"}})
    nxt = JsonDecisionRouterAction().execute(step, state, _runtime())

    assert nxt == "fallback"
    assert json.loads(state.last_model_response) == {"filters": {"data_type": "regular_code"}, "query": "class Foo"}


def test_json_decision_router_non_parsable_payload_keeps_original() -> None:
    step = StepDef(
        id="route",
        action="json_decision_router",
        raw={
            "id": "route",
            "action": "json_decision_router",
            "routes": {"direct": "direct_step"},
            "on_other": "fallback",
        },
    )

    state = _state_with_payload("not a json object")
    nxt = JsonDecisionRouterAction().execute(step, state, _runtime())

    assert nxt == "fallback"
    assert state.last_model_response == "not a json object"
