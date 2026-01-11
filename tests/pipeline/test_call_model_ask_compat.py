import pytest

from code_query_engine.pipeline.actions import call_model as cm


pytestmark = pytest.mark.unit


class KeywordOnlyPromptModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def ask(
        self,
        *,
        prompt: str,
        consultant: str,
        system_prompt=None,
        max_tokens=None,
        temperature=None,
    ) -> str:
        self.calls.append({"prompt": prompt, "consultant": consultant})
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
        self.calls.append({"context": context, "question": question, "consultant": consultant})
        return "OK_CTXQ"


def test_call_model_compat_uses_keywords_when_signature_introspection_fails_prompt(monkeypatch: pytest.MonkeyPatch):
    """
    Regression test:
    If inspect.signature() fails (e.g., some callables / wrappers),
    _call_model_ask_with_compat must NOT fall back to positional calls
    for a keyword-only model.
    """
    m = KeywordOnlyPromptModel()

    def _boom(_obj):
        raise RuntimeError("signature introspection disabled")

    monkeypatch.setattr(cm.inspect, "signature", _boom)

    out = cm._call_model_ask_with_compat(
        m,
        prompt="P",
        context="C",
        question="Q",
        consultant="router_v1",
        system_prompt="",
    )

    assert out == "OK_PROMPT"
    assert m.calls == [{"prompt": "P", "consultant": "router_v1"}]


def test_call_model_compat_uses_keywords_when_signature_introspection_fails_context_question(monkeypatch: pytest.MonkeyPatch):
    """
    Same as above, but for the alternate keyword-only signature:
      ask(context=..., question=..., consultant=...)
    """
    m = KeywordOnlyContextQuestionModel()

    def _boom(_obj):
        raise RuntimeError("signature introspection disabled")

    monkeypatch.setattr(cm.inspect, "signature", _boom)

    out = cm._call_model_ask_with_compat(
    m,
    prompt="P",
    context="C",
    question="Q",
    consultant="router_v1",
    system_prompt="",
)


    assert out == "OK_CTXQ"
    assert m.calls == [{"context": "C", "question": "Q", "consultant": "router_v1"}]
