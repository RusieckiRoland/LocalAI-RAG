from types import SimpleNamespace

import pytest

from code_query_engine.pipeline.actions.call_model import CallModelAction


class _CaptureRenderer:
    def __init__(self):
        self.calls = []

    def render(self, *, profile: str, context: str, question: str, history: str = "") -> str:
        # The whole point: these MUST be strings, not "<bound method ...>"
        assert isinstance(context, str)
        assert isinstance(question, str)
        assert isinstance(history, str)

        assert "<bound method" not in context
        assert "<bound method" not in question
        assert "<bound method" not in history

        self.calls.append(
            {
                "profile": profile,
                "context": context,
                "question": question,
                "history": history,
            }
        )
        return "PROMPT"


class _CaptureModel:
    def __init__(self):
        self.prompts = []

    def ask(self, *, consultant: str, prompt: str, **kwargs):
        self.prompts.append({"consultant": consultant, "prompt": prompt})
        return "[DIRECT:]"


def test_call_model_uses_state_methods_not_bound_methods(monkeypatch):
    # Arrange: capture renderer + model
    renderer = _CaptureRenderer()
    model = _CaptureModel()

    # Monkeypatch PromptRendererFactory.create used inside call_model.py
    import code_query_engine.pipeline.actions.call_model as call_model_mod

    def _fake_create(*, model_path: str, prompts_dir: str, system_prompt: str):
        # Ensure system_prompt is passed to factory (contract)
        assert system_prompt == "SYS_FROM_SETTINGS"
        return renderer

    monkeypatch.setattr(call_model_mod.PromptRendererFactory, "create", staticmethod(_fake_create))

    # State: methods MUST be called by the action
    class _State:
        consultant = "e2e_scenarios_runner"
        last_model_response = ""

        def composed_context_for_prompt(self) -> str:
            return "CTX"

        def history_for_prompt(self) -> str:
            return "HIST"

        def model_input_en_or_fallback(self) -> str:
            return "QUESTION"

    state = _State()

    # Minimal step/runtime doubles
    step = SimpleNamespace(id="s1", raw={"prompt_key": "rejewski/router_v1"}, next=None)

    runtime = SimpleNamespace(
        pipeline_settings={"prompts_dir": "prompts", "system_prompt": "SYS_FROM_SETTINGS"},
        model_path="some-model",
        model=model,
    )

    # Act
    action = CallModelAction()
    action.do_execute(step, state, runtime)

    # Assert: renderer got the correct strings
    assert renderer.calls == [
        {
            "profile": "rejewski/router_v1",
            "context": "CTX",
            "question": "QUESTION",
            "history": "HIST",
        }
    ]

    # And model saw the final prompt
    assert model.prompts and model.prompts[0]["prompt"] == "PROMPT"
