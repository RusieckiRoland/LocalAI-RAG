import pytest

from code_query_engine.pipeline.actions.call_model import CallModelAction
from code_query_engine.pipeline.engine import PipelineRuntime


class _CaptureModel:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ask(self, *, prompt: str, system_prompt=None, **kwargs):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "kwargs": dict(kwargs)})
        return "OK"


def test_call_model_max_output_tokens_overrides_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _CaptureModel()

    # Avoid file I/O and prompt formatting complexity.
    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")
    monkeypatch.setattr(CallModelAction, "_build_manual_prompt", staticmethod(lambda **_kw: "PROMPT"))

    runtime = PipelineRuntime(
        pipeline_settings={"prompts_dir": "dummy"},
        model=model,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=None,
        constants=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    class _State:
        consultant = "c"
        last_model_response = ""
        context_blocks = ["CTX"]
        user_question_neutral = "Q"
        history_dialog = []

    state = _State()

    step = type(
        "S",
        (),
        {
            "raw": {
                "prompt_key": "x",
                "user_parts": {
                    "evidence": {"source": "context_blocks", "template": "{}"},
                    "user_question": {"source": "user_question_neutral", "template": "{}"},
                },
                "max_tokens": 999,
                "max_output_tokens": 123,
            }
        },
    )()

    CallModelAction().do_execute(step, state, runtime)

    assert model.calls
    assert model.calls[0]["kwargs"].get("max_tokens") == 123

