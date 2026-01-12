from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import constants

from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator

from history.history_manager import HistoryManager
from history.mock_redis import InMemoryMockRedis


class DummyInteractionLogger:
    def log_interaction(self, *args: Any, **kwargs: Any) -> None:
        return


class DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class DummyMarkdownTranslator:
    def translate_markdown(self, text: str) -> str:
        return text


class FakeTokenCounter:
    def __init__(self, fixed_count: int) -> None:
        self.fixed_count = fixed_count

    def count(self, text: str) -> int:
        return self.fixed_count

    def count_tokens(self, text: str) -> int:
        return self.fixed_count


class FakeModelWithAsk:
    """
    call_model uses model.ask(...). Allow both positional and keyword usage.
    Queue is per consultant.
    """

    def __init__(self, *, outputs_by_consultant: Dict[str, List[str]]) -> None:
        self._outs = {k: list(v or []) for k, v in (outputs_by_consultant or {}).items()}

    def ask(self, *args: Any, **kwargs: Any) -> str:
        consultant = kwargs.get("consultant")
        if not consultant and args:
            # If someone passed consultant positionally, try best-effort.
            # We only support keyword in our tests; fall back to state's consultant naming.
            consultant = "rejewski"

        q = self._outs.get(str(consultant), [])
        if not q:
            return ""
        return str(q.pop(0))


class FakeRetriever:
    def __init__(self, *, results: List[Dict[str, Any]]) -> None:
        self._results = list(results or [])
        self.calls: List[Dict[str, Any]] = []

    def search(self, *, query: str, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "top_k": top_k})
        return list(self._results)


class DummyRetrievalDispatcher:
    def __init__(self, *, retriever: FakeRetriever) -> None:
        self._retriever = retriever

    def search(self, decision: Any, *, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = getattr(decision, "query", None) or ""
        return self._retriever.search(query=str(query), top_k=int(top_k), settings=settings, filters=filters)


class FakeGraphProvider:
    def __init__(self, *, expand_result: Optional[Dict[str, Any]] = None, node_texts: Optional[List[Dict[str, Any]]] = None) -> None:
        self._expand_result = dict(expand_result or {"nodes": [], "edges": []})
        self._node_texts = list(node_texts or [])

    def expand_dependency_tree(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return dict(self._expand_result)

    def fetch_node_texts(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return list(self._node_texts)


def _load_pipe_from_inline_yaml(tmp_path: Path, yaml_text: str, name: str) -> Any:
    yaml_path = tmp_path / f"{name}.yaml"
    yaml_path.write_text(textwrap.dedent(yaml_text).strip(), encoding="utf-8")

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)
    return pipe


def _runtime(
    *,
    pipeline_settings: Dict[str, Any],
    model: Any,
    dispatcher: Any,
    history_manager: HistoryManager,
    token_counter: Optional[Any] = None,
    graph_provider: Optional[Any] = None,
) -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings=pipeline_settings,
        model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=history_manager,
        logger=DummyInteractionLogger(),
        constants=constants,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=graph_provider,
        token_counter=token_counter,
        add_plant_link=lambda text, consultant=None: text,
    )


def _run_engine(pipe: Any, state: PipelineState, rt: PipelineRuntime) -> Any:
    # HistoryManager requires start_user_query before set_final_answer() is called (finalize persists history).
    try:
        rt.history_manager.start_user_query(state.user_query, None)
    except Exception:
        pass

    if not hasattr(state, "turn_loop_counter"):
        setattr(state, "turn_loop_counter", 0)

    engine = PipelineEngine(build_default_action_registry())
    return engine.run(pipe, state, rt)


def test_e2e_budget_over_limit_fallback_summarizes(tmp_path: Path) -> None:
    yaml_text = """
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
          next: call_answer

        - id: call_answer
          action: call_model
          prompt_key: "e2e/answer_v1"
          next: handle_answer

        - id: handle_answer
          action: prefix_router
          answer_prefix: "[Answer:]"
          on_answer: finalize
          on_other: finalize
          next: finalize

        - id: finalize
          action: finalize
          end: true
    """

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_budget_over_limit")

    model = FakeModelWithAsk(outputs_by_consultant={"rejewski": ["[Answer:] OK (budget)"]})
    retriever = FakeRetriever(results=[])
    dispatcher = DummyRetrievalDispatcher(retriever=retriever)

    history_manager = HistoryManager(backend=InMemoryMockRedis(), session_id="s")
    # Make history non-empty, so load_history has something to work with.
    history_manager.start_user_query("PREV QUESTION", None)
    history_manager.set_final_answer("PREV ANSWER", None)

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
        history_manager=history_manager,
        token_counter=FakeTokenCounter(fixed_count=9999),
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
    yaml_text = """
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
          action: prefix_router
          bm25_prefix: "[BM25:]"
          semantic_prefix: "[SEMANTIC:]"
          hybrid_prefix: "[HYBRID:]"
          semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
          direct_prefix: "[DIRECT:]"
          on_bm25: fetch
          on_semantic: fetch
          on_hybrid: fetch
          on_semantic_rerank: fetch
          on_direct: call_answer
          on_other: call_answer
          next: call_answer

        - id: fetch
          action: fetch_more_context
          next: call_answer

        - id: call_answer
          action: call_model
          prompt_key: "e2e/answer_v1"
          next: handle_answer

        - id: handle_answer
          action: prefix_router
          answer_prefix: "[Answer:]"
          on_answer: finalize
          on_other: finalize
          next: finalize

        - id: finalize
          action: finalize
          end: true
    """

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_direct_path")

    model = FakeModelWithAsk(outputs_by_consultant={"rejewski": ["[DIRECT:]", "[Answer:] OK DIRECT"]})
    retriever = FakeRetriever(results=[])
    dispatcher = DummyRetrievalDispatcher(retriever=retriever)

    history_manager = HistoryManager(backend=InMemoryMockRedis(), session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
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
    yaml_text = """
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
          action: prefix_router
          bm25_prefix: "[BM25:]"
          semantic_prefix: "[SEMANTIC:]"
          hybrid_prefix: "[HYBRID:]"
          semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
          direct_prefix: "[DIRECT:]"
          on_bm25: fetch
          on_semantic: fetch
          on_hybrid: fetch
          on_semantic_rerank: fetch
          on_direct: call_answer
          on_other: call_answer
          next: call_answer

        - id: fetch
          action: fetch_more_context
          next: call_answer

        - id: call_answer
          action: call_model
          prompt_key: "e2e/answer_v1"
          next: handle_answer

        - id: handle_answer
          action: prefix_router
          answer_prefix: "[Answer:]"
          on_answer: finalize
          on_other: finalize
          next: finalize

        - id: finalize
          action: finalize
          end: true
    """

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_bm25_path")

    model = FakeModelWithAsk(outputs_by_consultant={"rejewski": ["[BM25:] query", "[Answer:] OK BM25"]})

    retriever = FakeRetriever(results=[{"path": "a.py", "content": "print('a')"}])
    dispatcher = DummyRetrievalDispatcher(retriever=retriever)
    history_manager = HistoryManager(backend=InMemoryMockRedis(), session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
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
    assert retriever.calls, "BM25 path should trigger retrieval"


def test_e2e_dependency_expand_then_fetch_node_texts(tmp_path: Path) -> None:
    yaml_text = """
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
          next: handle_answer

        - id: handle_answer
          action: prefix_router
          answer_prefix: "[Answer:]"
          on_answer: finalize
          on_other: finalize
          next: finalize

        - id: finalize
          action: finalize
          end: true
    """

    pipe = _load_pipe_from_inline_yaml(tmp_path, yaml_text, "e2e_dep_expand")

    model = FakeModelWithAsk(outputs_by_consultant={"rejewski": ["[Answer:] OK DEP GRAPH"]})

    retriever = FakeRetriever(results=[])
    dispatcher = DummyRetrievalDispatcher(retriever=retriever)

    graph = FakeGraphProvider(
        expand_result={"nodes": ["A", "B"], "edges": [{"from": "A", "to": "B"}]},
        node_texts=[{"id": "A", "text": "node A"}, {"id": "B", "text": "node B"}],
    )

    history_manager = HistoryManager(backend=InMemoryMockRedis(), session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
        history_manager=history_manager,
        graph_provider=graph,
    )

    state = PipelineState(
        user_query="dep expand please",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    # Seed nodes are commonly required by expand_dependency_tree.
    state.retrieval_seed_nodes = ["A"]

    out = _run_engine(pipe, state, rt)
    assert out.final_answer == "OK DEP GRAPH"
