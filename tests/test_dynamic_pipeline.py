import types
from typing import Any, Dict, List, Optional

import pytest

import constants
from common.utils import extract_followup
from code_query_engine.dynamic_pipeline import (
    PipelineContext,
    DynamicPipelineRunner,
)


# ---------- Fakes / test doubles ----------

class FakeModel:
    """Minimal fake LLM model capturing calls."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def ask(self, context: str, question: str, prompt_key: str) -> str:
        """Store call arguments and return a simple answer."""
        self.calls.append(
            {
                "context": context,
                "question": question,
                "prompt_key": prompt_key,
            }
        )
        # Return something prefixed as a normal ANSWER so that handle_prefix can parse it
        return f"{constants.ANSWER_PREFIX} Echo: {question}"


class FakeSearcher:
    """Minimal fake searcher returning predefined results."""

    def __init__(self, results: List[Dict[str, Any]]) -> None:
        self._results = results
        self.last_query: Optional[Dict[str, Any]] = None

    def search(self, query: str, top_k: int = 5, **kwargs) -> List[Dict[str, Any]]:
        """Capture search query (including mode-specific kwargs) and return prepared results."""
        recorded: Dict[str, Any] = {"query": query, "top_k": top_k}
        # Store any keyword arguments so tests can assert on them (e.g. alpha/beta for vector mode).
        recorded.update(kwargs)
        self.last_query = recorded
        return list(self._results)


class FakeMarkdownTranslator:
    """Fake markdown translator for EN->PL."""

    def translate_markdown(self, text: str) -> str:
        return f"[PL]{text}"


class FakeTranslatorPlEn:
    """Fake translator for PL->EN."""

    def translate(self, text: str) -> str:
        return f"[EN]{text}"


class FakeHistoryManager:
    """Minimal fake of HistoryManager used only by PipelineContext."""

    def __init__(self) -> None:
        self._context_blocks: List[str] = []
        self.started: List[Dict[str, str]] = []
        self.final_answers: List[Dict[str, Optional[str]]] = []

    def get_context_blocks(self) -> List[str]:
        return list(self._context_blocks)

    def start_user_query(self, model_input_en: str, original_query: str) -> None:
        self.started.append(
            {
                "model_input_en": model_input_en,
                "original_query": original_query,
            }
        )

    def set_final_answer(self, ans_en: str, ans_pl: Optional[str]) -> None:
        self.final_answers.append({"ans_en": ans_en, "ans_pl": ans_pl})

    # Helper for tests to inject context
    def add_context_block(self, block: str) -> None:
        self._context_blocks.append(block)


class FakeLogger:
    """Fake InteractionLogger."""

    def log_interaction(
        self,
        original_question: str,
        model_input_en: str,
        codellama_response: str,
        followup_query: Optional[str],
        query_type: str,
        final_answer: Optional[str],
        context_blocks: List[str],
        next_codellama_prompt: Optional[str],
    ) -> None:
        # For tests we do not need to persist anything.
        pass


# ---------- Helpers ----------

def make_pipeline_context_and_runner(
    *,
    settings: Optional[Dict[str, Any]] = None,
    search_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Create a PipelineContext + DynamicPipelineRunner + fakes for tests.
    Returns a dict with all objects.
    """
    settings = settings or {}
    search_results = search_results or []

    fake_model = FakeModel()
    fake_searcher = FakeSearcher(search_results)
    fake_markdown = FakeMarkdownTranslator()
    fake_pl_en = FakeTranslatorPlEn()
    fake_history = FakeHistoryManager()
    fake_logger = FakeLogger()

    ctx = PipelineContext(
        user_query="Gdzie jest punkt wejścia aplikacji web?",
        session_id="sess-1",
        consultant="rejewski",
        branch="stable",
        translate_chat=True,
        main_model=fake_model,
        searcher=fake_searcher,
        markdown_translator=fake_markdown,
        translator_pl_en=fake_pl_en,
        history_manager=fake_history,
        settings=settings,
    )

    runner = DynamicPipelineRunner(
        pipelines_dir=".",  # not used in these tests
        main_model=fake_model,
        searcher=fake_searcher,
        markdown_translator=fake_markdown,
        translator_pl_en=fake_pl_en,
        logger=fake_logger,
    )

    return {
        "ctx": ctx,
        "runner": runner,
        "fake_model": fake_model,
        "fake_searcher": fake_searcher,
        "fake_history": fake_history,
    }


# ---------- Tests: extract_followup ----------

def test_extract_followup_default_prefix_uses_constants():
    """extract_followup should use constants.FOLLOWUP_PREFIX by default."""
    text = f"{constants.FOLLOWUP_PREFIX} C# Program.cs Main"
    result = extract_followup(text)
    assert result == "C# Program.cs Main"


def test_extract_followup_custom_prefix():
    """extract_followup should respect custom followup_prefix when provided."""
    text = "###FOLLOWUP### some query here"
    result = extract_followup(text, followup_prefix="###FOLLOWUP###")
    assert result == "some query here"


# ---------- Tests: _step_handle_prefix (prefixes from YAML) ----------

def test_handle_prefix_uses_yaml_answer_and_followup_prefixes_answer_branch():
    """_step_handle_prefix should detect answer using YAML answer_prefix."""
    env = make_pipeline_context_and_runner(
        settings={
            "answer_prefix": "<<ANS>>",
            "followup_prefix": "<<FUP>>",
        }
    )
    ctx = env["ctx"]
    runner = env["runner"]

    ctx.last_response = "<<ANS>> Final answer from model"

    step = {
        "action": "handle_prefix",
        "on_answer": "finalize",
        "on_followup": "fetch_more",
        "on_other": "other",
    }

    next_step = runner._step_handle_prefix(step, ctx)

    assert next_step == "finalize"
    assert ctx.answer_en == "Final answer from model"
    assert ctx.query_type == "direct answer"


def test_handle_prefix_uses_yaml_answer_and_followup_prefixes_followup_branch():
    """_step_handle_prefix should detect followup using YAML followup_prefix."""
    env = make_pipeline_context_and_runner(
        settings={
            "answer_prefix": "<<ANS>>",
            "followup_prefix": "<<FUP>>",
        }
    )
    ctx = env["ctx"]
    runner = env["runner"]

    ctx.last_response = "<<FUP>> C# Program.cs Main"

    step = {
        "action": "handle_prefix",
        "on_answer": "finalize",
        "on_followup": "fetch_more",
        "on_other": "other",
    }

    next_step = runner._step_handle_prefix(step, ctx)

    # For followup path we do not set answer_en yet; we just route to next step.
    assert next_step == "fetch_more"
    assert ctx.answer_en is None
    assert ctx.query_type == "unknown"


# ---------- Tests: _step_call_model (prompt per step) ----------

def test_call_model_uses_prompt_key_from_step():
    """_step_call_model should use per-step prompt_key instead of consultant."""
    env = make_pipeline_context_and_runner()
    ctx = env["ctx"]
    runner = env["runner"]
    fake_model = env["fake_model"]

    ctx.model_input_en = "[EN]Where is web app entry point?"
    step = {
        "action": "call_model",
        "id": "call_model_initial",
        "prompt_key": "rejewski_code_v1",
    }

    runner._step_call_model(step, ctx)

    assert fake_model.calls, "Model.ask should have been called exactly once."
    call = fake_model.calls[-1]
    assert call["prompt_key"] == "rejewski_code_v1"
    # Question should be the translated model_input_en
    assert "[EN]Where is web app entry point?" in call["question"]


def test_call_model_falls_back_to_consultant_when_prompt_key_missing():
    """If step.prompt_key is missing, _step_call_model should fall back to consultant."""
    env = make_pipeline_context_and_runner()
    ctx = env["ctx"]
    runner = env["runner"]
    fake_model = env["fake_model"]

    ctx.model_input_en = "[EN]Where is web app entry point?"
    step = {
        "action": "call_model",
        "id": "call_model_initial",
        # no prompt_key here
    }

    runner._step_call_model(step, ctx)

    assert fake_model.calls, "Model.ask should have been called."
    call = fake_model.calls[-1]
    assert call["prompt_key"] == "rejewski"  # consultant is used as fallback


def test_call_model_uses_default_prompt_key_when_step_missing():
    """
    If step.prompt_key is missing but settings.default_prompt_key is set,
    _step_call_model should use that default prompt key.
    """
    env = make_pipeline_context_and_runner(
        settings={
            "default_prompt_key": "ada_default",
        }
    )
    ctx = env["ctx"]
    runner = env["runner"]
    fake_model = env["fake_model"]

    ctx.model_input_en = "[EN]Where is web app entry point?"
    step = {
        "action": "call_model",
        "id": "call_model_initial",
        # no prompt_key here
    }

    runner._step_call_model(step, ctx)

    assert fake_model.calls, "Model.ask should have been called."
    call = fake_model.calls[-1]
    assert call["prompt_key"] == "ada_default"




# ---------- Tests: _step_fetch_more_context (prefix + search_mode) ----------

def test_fetch_more_context_uses_followup_prefix_and_extends_context():
    """
    _step_fetch_more_context should:
    - extract followup using YAML followup_prefix,
    - perform search via searcher,
    - append compressed context text to ctx.context_blocks,
    - set query_type to 'vector query'.
    """
    fake_results = [
        {
            "File": "src/app/Program.cs",
            "Content": "public class Program { static void Main() {} }",
            "Member": None,
            "Namespace": "App",
            "Class": "Program",
            "HitLines": [1, 5],
            "Rank": 1,
            "Distance": 0.1,
            "Related": [],
        }
    ]

    env = make_pipeline_context_and_runner(
        settings={
            "followup_prefix": "[Requesting data on:]",
        },
        search_results=fake_results,
    )
    ctx = env["ctx"]
    runner = env["runner"]
    fake_searcher = env["fake_searcher"]

    ctx.last_response = "[Requesting data on:] C# Program.cs Main"
    # Initially no context
    assert ctx.context_blocks == []

    step = {
        "action": "fetch_more_context",
        "id": "fetch_more_context",
        "search_mode": "hybrid",
    }

    runner._step_fetch_more_context(step, ctx)

    # searcher should have been called with extracted followup
    assert fake_searcher.last_query is not None
    assert fake_searcher.last_query["query"] == "C# Program.cs Main"
    assert fake_searcher.last_query["top_k"] == 5

    # context_blocks should now contain exactly one compressed block
    assert len(ctx.context_blocks) == 1
    assert isinstance(ctx.context_blocks[0], str)
    assert ctx.query_type == "vector query"


def test_fetch_more_context_respects_search_mode_from_step():
    """
    _step_fetch_more_context should read search_mode from step first.
    When step overrides to 'vector', we call the searcher in vector-only mode.
    """
    fake_results: List[Dict[str, Any]] = []

    env = make_pipeline_context_and_runner(
        settings={
            "followup_prefix": "[Requesting data on:]",
            "search_mode": "hybrid",  # pipeline default
        },
        search_results=fake_results,
    )
    ctx = env["ctx"]
    runner = env["runner"]
    fake_searcher = env["fake_searcher"]

    ctx.last_response = "[Requesting data on:] some followup"
    step = {
        "action": "fetch_more_context",
        "id": "fetch_more_context",
        "search_mode": "vector",  # step-level override
    }

    runner._step_fetch_more_context(step, ctx)

    # Vector mode should still call search, but with vector-only parameters.
    assert fake_searcher.last_query is not None
    assert fake_searcher.last_query["query"] == "some followup"
    assert fake_searcher.last_query.get("alpha") == 1.0
    assert fake_searcher.last_query.get("beta") == 0.0
    assert ctx.query_type == "vector query"
