# tests/test_call_model_action_uses_state_methods.py
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import constants

import code_query_engine.pipeline.actions.call_model as call_model_mod
from code_query_engine.pipeline.actions.call_model import CallModelAction
from code_query_engine.pipeline.engine import PipelineRuntime


class DummyMarkdownTranslator:
    def translate_en_pl(self, text: str) -> str:
        return text


class DummyTranslator:
    def translate_pl_en(self, text: str) -> str:
        return text


class NoopInteractionLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        return

    def debug(self, *args: Any, **kwargs: Any) -> None:
        return

    def warning(self, *args: Any, **kwargs: Any) -> None:
        return

    def error(self, *args: Any, **kwargs: Any) -> None:
        return


class InMemoryHistory:
    def load_history_for_prompt(self, *args: Any, **kwargs: Any) -> str:
        return ""

    def set_final_answer(self, *args: Any, **kwargs: Any) -> None:
        return


class StubModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def ask(self, *, consultant: str, prompt: str, **kwargs: Any) -> str:
        self.calls.append((consultant, prompt))
        return "MODEL_OUT"


class CapturingRenderer:
    def __init__(self, expected_context: str, expected_question: str, expected_history: str) -> None:
        self.expected_context = expected_context
        self.expected_question = expected_question
        self.expected_history = expected_history

    def render(self, *, profile: str, context: str, question: str, history: str = "") -> str:
        # Regression guard: must NOT receive bound methods / callables.
        assert isinstance(context, str), f"context must be str, got: {type(context)!r} value={context!r}"
        assert isinstance(question, str), f"question must be str, got: {type(question)!r} value={question!r}"
        assert isinstance(history, str), f"history must be str, got: {type(history)!r} value={history!r}"

        assert "bound method" not in context
        assert "bound method" not in question
        assert "bound method" not in history

        assert context == self.expected_context
        assert question == self.expected_question
        assert history == self.expected_history

        return "PROMPT_FROM_RENDERER"


@pytest.mark.parametrize(
    "context_value,history_value,question_value",
    [
        # 1) methods on state (this is the regression that broke you)
        ("METHOD", "METHOD", "METHOD"),
        # 2) mixed: context method, history empty, question method
        ("METHOD", "", "METHOD"),
        # 3) plain strings (still must work)
        ("STRING", "STRING", "STRING"),
    ],
)
def test_call_model_action_uses_state_methods_not_bound_method_strings(
    monkeypatch: pytest.MonkeyPatch,
    context_value: str,
    history_value: str,
    question_value: str,
) -> None:
    expected_context = "CTX"
    expected_history = "HIST"
    expected_question = "Q"

    # Build a fake PipelineState-like object with either methods or plain strings.
    class State:
        consultant = "e2e_scenarios_runner"

        # keep fields used by CallModelAction
        last_model_response: str | None = None

        def composed_context_for_prompt(self) -> str:
            return expected_context

        def history_for_prompt(self) -> str:
            return expected_history

        def model_input_en_or_fallback(self) -> str:
            return expected_question

    state = State()

    if context_value == "STRING":
        state.composed_context_for_prompt = expected_context  # type: ignore[assignment]
    if history_value == "":
        state.history_for_prompt = ""  # type: ignore[assignment]
        expected_history_local = ""
    elif history_value == "STRING":
        state.history_for_prompt = expected_history  # type: ignore[assignment]
        expected_history_local = expected_history
    else:
        expected_history_local = expected_history

    if question_value == "STRING":
        state.model_input_en_or_fallback = expected_question  # type: ignore[assignment]

    expected_context_local = expected_context if context_value != "STRING" else expected_context
    expected_question_local = expected_question if question_value != "STRING" else expected_question

    model = StubModel()

    # Monkeypatch PromptRendererFactory.create to return our capturing renderer,
    # so we don't depend on prompt files on disk.
    def _fake_create(*, model_path: str, prompts_dir: str, system_prompt: str) -> Any:
        return CapturingRenderer(
            expected_context=expected_context_local,
            expected_question=expected_question_local,
            expected_history=expected_history_local,
        )

    monkeypatch.setattr(call_model_mod.PromptRendererFactory, "create", _fake_create)

    runtime = PipelineRuntime(
        pipeline_settings={
            "model_path": "dummy-model",
            "prompts_dir": "dummy-prompts",
            "system_prompt": "SYS",
        },
        model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=InMemoryHistory(),
        logger=NoopInteractionLogger(),
        constants=constants,
        retrieval_dispatcher=None,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    step = SimpleNamespace(raw={"prompt_key": "rejewski/router_v1"}, next=None)

    action = CallModelAction()
    action.do_execute(step, state, runtime)

    # The model must receive the renderer-produced prompt.
    assert model.calls, "Model.ask was not called"
    assert model.calls[0][0] == "e2e_scenarios_runner"
    assert model.calls[0][1] == "PROMPT_FROM_RENDERER"
    assert state.last_model_response == "MODEL_OUT"
