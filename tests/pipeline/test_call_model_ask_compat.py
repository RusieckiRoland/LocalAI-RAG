# tests/pipeline/test_call_model_ask_compat.py

import pytest

from code_query_engine.pipeline.actions.call_model import CallModelAction
from code_query_engine.pipeline.actions import call_model as cm


pytestmark = pytest.mark.unit


class KeywordOnlyPromptModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def ask(
        self,
        *,
        prompt: str,
        system_prompt=None,
        max_tokens=None,
        temperature=None,
    ) -> str:
        self.calls.append({"prompt": prompt})
        return "OK_PROMPT"


class KeywordOnlyContextQuestionModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def ask(
        self,
        *,
        context: str,
        question: str,
        consultant: str,
        system_prompt=None,
        max_tokens=None,
        temperature=None,
    ) -> str:
        # This signature is no longer supported by CallModelAction.ask_manual_prompt_llm,
        # which always calls model.ask(prompt=...).
        self.calls.append({"context": context, "question": question, "consultant": consultant})
        return "OK_CTXQ"


def test_call_model_manual_prompt_uses_keywords_even_if_signature_introspection_fails(monkeypatch: pytest.MonkeyPatch):
    """
    Regression test (new contract):
    Even if inspect.signature() is unavailable, manual prompt calls must still work
    for a keyword-only prompt model, because we call model.ask(prompt=...) using keywords.
    """
    m = KeywordOnlyPromptModel()

    def _boom(_obj):
        raise RuntimeError("signature introspection disabled")

    monkeypatch.setattr(cm.inspect, "signature", _boom)

    action = CallModelAction()
    out = action.ask_manual_prompt_llm(model=m, rendered_prompt="P", model_kwargs={})

    assert out == "OK_PROMPT"
    assert m.calls == [{"prompt": "P"}]


def test_call_model_manual_prompt_rejects_context_question_signature(monkeypatch: pytest.MonkeyPatch):
    """
    New strict behavior:
    Models that only support ask(context=..., question=...) are NOT compatible with manual prompt mode,
    because the action calls model.ask(prompt=...).
    """
    m = KeywordOnlyContextQuestionModel()

    action = CallModelAction()

    with pytest.raises(TypeError):
        action.ask_manual_prompt_llm(model=m, rendered_prompt="P", model_kwargs={})
