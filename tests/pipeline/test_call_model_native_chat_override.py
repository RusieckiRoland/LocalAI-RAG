import pytest

from code_query_engine.pipeline.actions.call_model import CallModelAction
from code_query_engine.pipeline.engine import PipelineRuntime


class _CaptureModel:
    def __init__(self) -> None:
        self.ask_calls: list[dict] = []
        self.ask_chat_calls: list[dict] = []

    def ask(self, *, prompt: str, system_prompt=None, **kwargs):
        self.ask_calls.append({"prompt": prompt, "system_prompt": system_prompt, "kwargs": dict(kwargs)})
        return "OK"

    def ask_chat(self, *, prompt: str, history=None, system_prompt: str, **kwargs):
        self.ask_chat_calls.append(
            {"prompt": prompt, "history": history, "system_prompt": system_prompt, "kwargs": dict(kwargs)}
        )
        return "OK"


def _runtime(*, model: _CaptureModel, pipeline_settings: dict) -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings=pipeline_settings,
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
    history_dialog = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]


def test_call_model_uses_pipeline_settings_native_chat_when_step_omits_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _CaptureModel()
    runtime = _runtime(model=model, pipeline_settings={"prompts_dir": "dummy", "native_chat": True})

    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")

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
            }
        },
    )()

    CallModelAction().do_execute(step, _State(), runtime)

    assert not model.ask_calls
    assert model.ask_chat_calls


def test_call_model_step_native_chat_false_overrides_pipeline_settings_true(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _CaptureModel()
    runtime = _runtime(model=model, pipeline_settings={"prompts_dir": "dummy", "native_chat": True})

    monkeypatch.setattr(CallModelAction, "_load_system_prompt", lambda self, *, prompts_dir, prompt_key: "SYS")
    monkeypatch.setattr(CallModelAction, "_build_manual_prompt", staticmethod(lambda **_kw: "PROMPT"))

    step = type(
        "S",
        (),
        {
            "raw": {
                "prompt_key": "x",
                "native_chat": False,
                "user_parts": {
                    "evidence": {"source": "context_blocks", "template": "{}"},
                    "user_question": {"source": "user_question_neutral", "template": "{}"},
                },
            }
        },
    )()

    CallModelAction().do_execute(step, _State(), runtime)

    assert model.ask_calls
    assert not model.ask_chat_calls

