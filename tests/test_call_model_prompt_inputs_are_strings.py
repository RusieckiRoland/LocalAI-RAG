from __future__ import annotations

from types import SimpleNamespace

import pytest

from code_query_engine.pipeline.actions.call_model import CallModelAction
from prompt_builder.factory import PromptRendererFactory


class _CaptureModel:
    def __init__(self) -> None:
        self.prompts = []

    def ask(self, *, prompt: str, system_prompt: str = "", **kwargs):
        self.prompts.append({"prompt": prompt, "system_prompt": system_prompt})
        return "[DIRECT:] ok"


def test_call_model_uses_state_methods_not_bound_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _CaptureModel()

    # Avoid file I/O in tests
    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")

    # Make renderer capture inputs and ensure they are strings (not bound methods)
    captured = {}

    def _render(*, profile: str, context: str, question: str, history: str = "") -> str:
        assert isinstance(context, str)
        assert isinstance(question, str)
        assert isinstance(history, list)

        assert "bound method" not in context
        assert "bound method" not in question
        

        captured["profile"] = profile
        captured["context"] = context
        captured["question"] = question
        captured["history"] = history
        return "PROMPT"

    def _fake_build_manual_prompt(*, prompt_format, system_prompt, user_part, history):
        assert isinstance(user_part, str)
        assert "bound method" not in user_part

        # In the new contract, history is a dialog list (not a string)
        assert isinstance(history, list)

        captured["user_part"] = user_part
        captured["history"] = history
        return "PROMPT"


    monkeypatch.setattr(CallModelAction, "_build_manual_prompt", staticmethod(_fake_build_manual_prompt))


    class _State:
        consultant = "e2e_scenarios_runner"
        last_model_response = ""

        # New call_model contract expects these fields (sources used in user_parts)
        context_blocks = ["CTX"]
        user_question_en = "QUESTION"
        history_dialog = []

        # Legacy helper methods (must NOT leak as bound methods)
        def composed_context_for_prompt(self) -> str:
            return "CTX"

        def history_for_prompt(self) -> str:
            return "HIST"

        def model_input_en_or_fallback(self) -> str:
            return "QUESTION"

    state = _State()

    runtime = SimpleNamespace(
        pipeline_settings={
            "model_path": "dummy.bin",
            "prompts_dir": "dummy-prompts",
            "system_prompt": "SYS_FROM_SETTINGS",
        },
        model=model,
        logger=SimpleNamespace(log_interaction=lambda **kwargs: None),
    )

    step = SimpleNamespace(
        raw={
            "prompt_key": "rejewski/router_v1",
            "user_parts": {
                "evidence": {"source": "context_blocks", "template": "{}"},
                "user_question": {"source": "user_question_en", "template": "{}"},
            },
            "use_history": True,
        }
    )

    CallModelAction().do_execute(step, state, runtime)

    assert isinstance(captured["user_part"], str)
    assert "CTX" in captured["user_part"]
    assert "QUESTION" in captured["user_part"]
    assert isinstance(captured["history"], list)



    assert model.prompts and model.prompts[0]["prompt"] == "PROMPT"
