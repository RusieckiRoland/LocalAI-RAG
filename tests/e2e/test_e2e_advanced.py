import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import constants
from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator
from code_query_engine.pipeline.providers.fakes import FakeModelClient, FakeRetriever
from history.history_manager import HistoryManager
from history.mock_redis import InMemoryMockRedis
from integrations.plant_uml.plantuml_check import add_plant_link


class NullInteractionLogger:
    def log_interaction(self, **kwargs: Any) -> None:
        return


class FakeTokenCounter:
    """
    Support both token counter method names to match whichever your code uses.
    """
    def __init__(self, fixed_count: int) -> None:
        self.fixed_count = fixed_count
        self.calls: List[str] = []

    def count(self, text: str) -> int:
        self.calls.append(text)
        return self.fixed_count

    def count_tokens(self, text: str) -> int:
        self.calls.append(text)
        return self.fixed_count


class DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class DummyMarkdownTranslator:
    def translate(self, text: str) -> str:
        return text


def _runtime(
    *,
    pipeline_settings: Dict[str, Any],
    model: Any,
    retriever: Any,
    history_manager: HistoryManager,
    token_counter: Optional[Any] = None,
    graph_provider: Optional[Any] = None,
) -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings=pipeline_settings,
        main_model=model,
        searcher=retriever,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=history_manager,
        logger=NullInteractionLogger(),  # required by persist_turn_and_finalize
        constants=constants,
        add_plant_link=add_plant_link,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=graph_provider,
        token_counter=token_counter,
    )


def _run_engine(pipe, state: PipelineState, rt: PipelineRuntime) -> PipelineState:
    engine = PipelineEngine(build_default_action_registry())
    engine.run(pipe, state, rt)
    return state


def _load_pipe_from_inline_yaml(tmp_path: Path, yaml_text: str, name: str):
    yaml_path = tmp_path / f"{name}.yaml"
    yaml_path.write_text(yaml_text.strip(), encoding="utf-8")

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)
    return pipe


def test_e2e_budget_over_limit_fallback_summarizes(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_budget_over_limit
          settings:
            entry_step_id: load_history
            context_budget_tokens: 100
            history_budget_tokens: 50
            test: true

          steps:
            - id: load_history
              action: load_conversation_history
              next: budget

            - id: budget
              action: check_context_budget
              input: "composed_context_for_prompt"
              max_tokens_from_settings: "context_budget_tokens"
              next: answer

            - id: answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: finalize

            - id: finalize
              action: finalize_heuristic
              next: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_budget_over_limit")

    model = FakeModelClient(outputs=["OK BUDGET OVER LIMIT FALLBACK"])
    retriever = FakeRetriever(results=[])

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    history_manager.start_user_query("PREV QUESTION " + ("x " * 5000), None)
    history_manager.set_final_answer("PREV ANSWER " + ("z" * 8000))

    token_counter = FakeTokenCounter(fixed_count=9999)

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        retriever=retriever,
        history_manager=history_manager,
        token_counter=token_counter,
    )

    state = PipelineState(
        user_query="Q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = _run_engine(pipe, state, rt)
    assert "OK" in (out.final_answer or "")


def test_e2e_router_direct_answer_path(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_direct_path
          settings:
            entry_step_id: load_history
            top_k: 2
            test: true

          steps:
            - id: load_history
              action: load_conversation_history
              next: call_router

            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              bm25_prefix: "[BM25:]"
              semantic_prefix: "[SEMANTIC:]"
              hybrid_prefix: "[HYBRID:]"
              semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
              direct_prefix: "[DIRECT:]"
              on_bm25: fetch
              on_other: call_answer
              next: call_answer

            - id: fetch
              action: fetch_more_context
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: finalize

            - id: finalize
              action: finalize_heuristic
              next: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_direct_path")

    model = FakeModelClient(outputs=["[DIRECT:]", f"{constants.ANSWER_PREFIX} OK DIRECT"])
    retriever = FakeRetriever(results=[])

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")
    history_manager.start_user_query("Hello", "Cześć")
    history_manager.set_final_answer("Hi!", "Cześć!")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        retriever=retriever,
        history_manager=history_manager,
    )

    state = PipelineState(
        user_query="What is this?",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = _run_engine(pipe, state, rt)
    assert out.final_answer == "OK DIRECT"


def test_e2e_router_bm25_fetch_more_context_path(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_bm25_path
          settings:
            entry_step_id: load_history
            top_k: 2
            test: true

          steps:
            - id: load_history
              action: load_conversation_history
              next: call_router

            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              bm25_prefix: "[BM25:]"
              semantic_prefix: "[SEMANTIC:]"
              hybrid_prefix: "[HYBRID:]"
              semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
              direct_prefix: "[DIRECT:]"
              on_bm25: fetch
              on_other: call_answer
              next: call_answer

            - id: fetch
              action: fetch_more_context
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: finalize

            - id: finalize
              action: finalize_heuristic
              next: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_bm25_path")

    model = FakeModelClient(outputs=["[BM25:] query", "OK BM25"])
    retriever = FakeRetriever(
        results=[
            {"path": "a.py", "content": "print('a')"},
            {"path": "b.py", "content": "print('b')"},
        ]
    )

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        retriever=retriever,
        history_manager=history_manager,
    )

    state = PipelineState(
        user_query="Find something",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = _run_engine(pipe, state, rt)
    assert out.final_answer == "OK BM25"


def test_e2e_dependency_expand_then_fetch_node_texts(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_dep_expand
          settings:
            entry_step_id: expand
            test: true

          steps:
            - id: expand
              action: expand_dependency_tree
              next: fetch_texts

            - id: fetch_texts
              action: fetch_node_texts
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: finalize

            - id: finalize
              action: finalize_heuristic
              next: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_dep_expand")

    model = FakeModelClient(outputs=["OK DEP GRAPH"])
    retriever = FakeRetriever(results=[])

    class FakeGraphProvider:
        def expand_dependency_tree(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            return {"nodes": ["A", "B"], "edges": [{"from": "A", "to": "B"}]}

        def fetch_node_texts(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
            return [{"id": "A", "text": "node A"}, {"id": "B", "text": "node B"}]

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        retriever=retriever,
        history_manager=history_manager,
        graph_provider=FakeGraphProvider(),
    )

    state = PipelineState(
        user_query="dep expand please",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = _run_engine(pipe, state, rt)
    assert out.final_answer == "OK DEP GRAPH"
