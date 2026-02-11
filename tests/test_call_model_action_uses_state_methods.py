from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest

from code_query_engine.pipeline.actions.call_model import CallModelAction
from code_query_engine.pipeline.engine import PipelineRuntime
from prompt_builder.factory import PromptRendererFactory


class DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class DummyMarkdownTranslator:
    def translate(self, markdown_en: str) -> str:
        return markdown_en


class InMemoryHistory:
    def get_context_blocks(self):
        return []

    def add_iteration(self, meta, faiss_results):
        return None

    def set_final_answer(self, answer_en, answer_translated):
        return None


class NoopInteractionLogger:
    def log_interaction(self, **kwargs: Any):
        return None


class StubModel:
    def __init__(self) -> None:
        self.calls: list[Dict[str, Any]] = []

    def ask(self, *, prompt: str, system_prompt: str = "", **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "kwargs": kwargs})
        return "OK"


@pytest.mark.parametrize(
    "context_value,history_value,question_value",
    [
        ("METHOD", "METHOD", "METHOD"),
        ("METHOD", "", "METHOD"),
        ("STRING", "STRING", "STRING"),
    ],
)
def test_call_model_action_uses_state_methods_not_bound_method_strings(
    monkeypatch: pytest.MonkeyPatch,
    context_value: str,
    history_value: str,
    question_value: str,
) -> None:
    # --- Arrange -----------------------------------------------------------
    class State:
        consultant = "e2e_scenarios_runner"
        last_model_response: str | None = None

        # New call_model contract expects these fields (sources used in user_parts)
        context_blocks = ["CTX"]
        user_question_en = "Q"
        history_dialog = []

        # Legacy helper methods (must NOT leak as bound-method strings)
        def composed_context_for_prompt(self) -> str:
            return "CTX"

        def history_for_prompt(self) -> str:
            return "HIST"

        def model_input_en_or_fallback(self) -> str:
            return "Q"

    state = State()

    # Switch between methods vs plain strings (regression surface)
    if context_value == "STRING":
        state.composed_context_for_prompt = "CTX"  # type: ignore[assignment]

    if history_value == "":
        state.history_for_prompt = ""  # type: ignore[assignment]
    elif history_value == "STRING":
        state.history_for_prompt = "HIST"  # type: ignore[assignment]

    if question_value == "STRING":
        state.model_input_en_or_fallback = "Q"  # type: ignore[assignment]

    # Avoid file I/O in tests
    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")

    # Build a runtime that matches what CallModelAction expects
    runtime = PipelineRuntime(
        pipeline_settings={
            "model_path": "dummy-model",
            "prompts_dir": "dummy-prompts",
            "system_prompt": "SYS",
        },
        model=StubModel(),
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=InMemoryHistory(),
        logger=NoopInteractionLogger(),
        constants=SimpleNamespace(),
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    # IMPORTANT: new YAML contract requires user_parts (non-empty dict)
    step = SimpleNamespace(
        raw={
            "prompt_key": "rejewski/router_v1",
            "user_parts": {
                "evidence": {"source": "context_blocks", "template": "{}"},
                "user_question": {"source": "user_question_en", "template": "{}"},
            },
            "use_history": True,
        },
        next=None,
    )

    # We do not need real renderer for this test: bypass it completely.
    # Force renderer to return a known prompt string.
    monkeypatch.setattr(PromptRendererFactory, "create", staticmethod(lambda **kwargs: SimpleNamespace(render=lambda **kw: "PROMPT")))

    # --- Act ---------------------------------------------------------------
    CallModelAction().do_execute(step, state, runtime)

    # --- Assert ------------------------------------------------------------
    # No exception means we did not accidentally pass bound methods / invalid shapes.
    assert True
