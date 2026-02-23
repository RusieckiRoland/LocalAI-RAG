from __future__ import annotations

import json

from code_query_engine.pipeline.actions.inbox_dispatcher import InboxDispatcherAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


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


def test_inbox_dispatcher_enqueues_filtered_and_renamed_payload() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "directives_key": "dispatch",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    "allow_keys": ["prioritization_mode", "policy"],
                    "rename": {"policy": "prioritization_mode"},
                }
            },
        },
    )

    state = _state_with_payload(
        {
            "dispatch": [
                {
                    "target_step_id": "fetch_node_texts",
                    "payload": {"policy": "seed_first", "x": 1},
                }
            ]
        }
    )

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == [
        {
            "target_step_id": "fetch_node_texts",
            "topic": "config",
            "payload": {"prioritization_mode": "seed_first"},
        }
    ]


def test_inbox_dispatcher_topic_fallback_and_payload_shorthand() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    "allow_keys": ["policy"],
                    "rename": {"policy": "prioritization_mode"},
                }
            },
        },
    )

    state = _state_with_payload({"dispatch": [{"id": "fetch_node_texts", "policy": "balanced"}]})

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == [
        {
            "target_step_id": "fetch_node_texts",
            "topic": "config",
            "payload": {"prioritization_mode": "balanced"},
        }
    ]


def test_inbox_dispatcher_drops_unknown_target_or_empty_payload() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {"fetch_node_texts": {"allow_keys": ["policy"]}},
        },
    )

    state = _state_with_payload(
        {
            "dispatch": [
                {"target_step_id": "unknown", "payload": {"policy": "x"}},
                {"target_step_id": "fetch_node_texts", "payload": {"x": 1}},
            ]
        }
    )

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == []


def test_inbox_dispatcher_topic_is_taken_from_directive() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    "allow_keys": ["policy"],
                }
            },
        },
    )

    state = _state_with_payload(
        {
            "dispatch": [
                {"target_step_id": "fetch_node_texts", "topic": "other", "payload": {"policy": "seed_first"}},
            ]
        }
    )

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == [
        {
            "target_step_id": "fetch_node_texts",
            "topic": "other",
            "payload": {"policy": "seed_first"},
        }
    ]


def test_inbox_dispatcher_accepts_single_directive_object() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    "allow_keys": ["policy"],
                }
            },
        },
    )

    state = _state_with_payload({"dispatch": {"target_step_id": "fetch_node_texts", "payload": {"policy": "balanced"}}})

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == [
        {
            "target_step_id": "fetch_node_texts",
            "topic": "config",
            "payload": {"policy": "balanced"},
        }
    ]


def test_inbox_dispatcher_parses_code_fenced_jsonish() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    "allow_keys": ["policy"],
                }
            },
        },
    )

    payload = """```json
{dispatch:{target_step_id:\"fetch_node_texts\",payload:{policy:\"seed_first\",},},}
```"""

    state = _state_with_payload(payload)

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == [
        {
            "target_step_id": "fetch_node_texts",
            "topic": "config",
            "payload": {"policy": "seed_first"},
        }
    ]


def test_inbox_dispatcher_requires_allow_keys() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    # missing allow_keys should result in no enqueue
                }
            },
        },
    )

    state = _state_with_payload({"dispatch": [{"target_step_id": "fetch_node_texts", "payload": {"policy": "seed_first"}}]})

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == []


def test_inbox_dispatcher_rename_collision_last_wins() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    "allow_keys": ["policy", "prioritization_mode"],
                    "rename": {"policy": "prioritization_mode"},
                }
            },
        },
    )

    state = _state_with_payload(
        {
            "dispatch": [
                {
                    "target_step_id": "fetch_node_texts",
                    "payload": {"policy": "seed_first", "prioritization_mode": "balanced"},
                }
            ]
        }
    )

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == [
        {
            "target_step_id": "fetch_node_texts",
            "topic": "config",
            "payload": {"prioritization_mode": "balanced"},
        }
    ]


def test_inbox_dispatcher_non_parsable_payload_is_ignored() -> None:
    step = StepDef(
        id="dispatch",
        action="inbox_dispatcher",
        raw={
            "id": "dispatch",
            "action": "inbox_dispatcher",
            "rules": {
                "fetch_node_texts": {
                    "topic": "config",
                    "allow_keys": ["policy"],
                }
            },
        },
    )

    state = _state_with_payload("not a json object")

    InboxDispatcherAction().execute(step, state, _runtime())

    assert state.inbox == []
