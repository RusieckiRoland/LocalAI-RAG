from __future__ import annotations

import pytest

from code_query_engine.pipeline.actions.call_model import CallModelAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


class _ModelStub:
    def ask_chat(self, *, prompt: str, history=None, system_prompt: str, **kwargs):
        return "MODEL_OK"


@pytest.fixture()
def _runtime() -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings={"prompts_dir": "prompts"},
        model=_ModelStub(),
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=None,
        constants=None,
        retrieval_backend=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )


@pytest.fixture()
def _state() -> PipelineState:
    return PipelineState(
        user_query="hello",
        session_id="s",
        consultant="rejewski",
        translate_chat=False,
    )


def test_call_model_sets_custom_banner_fields(monkeypatch: pytest.MonkeyPatch, _runtime: PipelineRuntime, _state: PipelineState) -> None:
    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")

    step = StepDef(
        id="call_model",
        action="call_model",
        raw={
            "id": "call_model",
            "action": "call_model",
            "prompt_key": "rejewski/direct_answer_v1",
            "native_chat": True,
            "custom_banner": {
                "neutral": "N_BANNER",
                "translated": "T_BANNER",
            },
        },
    )

    CallModelAction().execute(step, _state, _runtime)

    assert _state.banner_neutral == "N_BANNER"
    assert _state.banner_translated == "T_BANNER"


def test_call_model_clears_previous_banner_when_custom_banner_not_provided(
    monkeypatch: pytest.MonkeyPatch,
    _runtime: PipelineRuntime,
    _state: PipelineState,
) -> None:
    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")

    _state.banner_neutral = "OLD_N"
    _state.banner_translated = "OLD_T"

    step = StepDef(
        id="call_model",
        action="call_model",
        raw={
            "id": "call_model",
            "action": "call_model",
            "prompt_key": "rejewski/direct_answer_v1",
            "native_chat": True,
        },
    )

    CallModelAction().execute(step, _state, _runtime)

    assert _state.banner_neutral is None
    assert _state.banner_translated is None


def test_call_model_allows_partial_custom_banner(monkeypatch: pytest.MonkeyPatch, _runtime: PipelineRuntime, _state: PipelineState) -> None:
    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")

    step = StepDef(
        id="call_model",
        action="call_model",
        raw={
            "id": "call_model",
            "action": "call_model",
            "prompt_key": "rejewski/direct_answer_v1",
            "native_chat": True,
            "custom_banner": {
                "neutral": "N_ONLY",
            },
        },
    )

    CallModelAction().execute(step, _state, _runtime)

    assert _state.banner_neutral == "N_ONLY"
    assert _state.banner_translated is None
