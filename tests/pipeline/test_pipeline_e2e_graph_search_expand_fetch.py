from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import constants

from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter
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


class FakeModelWithAsk:
    """
    call_model uses model.ask(...). Allow both positional and keyword usage.
    Queue is per consultant.
    """

    def __init__(self, *, outputs_by_consultant: Dict[str, List[str]]) -> None:
        self._outs = {k: list(v or []) for k, v in (outputs_by_consultant or {}).items()}

    def ask(self, *args: Any, **kwargs: Any) -> str:
        consultant = kwargs.get("consultant") or "e2e_graph_search_expand_fetch"
        q = self._outs.get(str(consultant), [])
        if not q:
            return ""
        return str(q.pop(0))


class FakeRetriever:
    def __init__(self, *, results: List[Dict[str, Any]]) -> None:
        self._results = list(results or [])
        self.calls: List[Dict[str, Any]] = []

    def search(
        self, *, query: str, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "top_k": top_k})
        return list(self._results)


class DummyRetrievalDispatcher:
    def __init__(self, *, retriever: FakeRetriever) -> None:
        self._retriever = retriever

    def search(
        self, decision: Any, *, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        query = getattr(decision, "query", None) or ""
        return self._retriever.search(query=str(query), top_k=int(top_k), settings=settings, filters=filters)


class FakeGraphProvider:
    def expand_dependency_tree(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        # Minimal contract-compatible shape
        return {"nodes": [], "edges": []}

    def fetch_node_texts(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return []


def _load_pipeline(tmp_path: Path) -> Any:
    yaml_text = """
YAMLpipeline:
  name: e2e_graph_search_expand_fetch
  settings:
    entry_step_id: router
    repository: "nopCommerce"
    top_k: 2
    test: true

    max_context_tokens: 4096
    graph_max_depth: 2
    graph_max_nodes: 200
    graph_edge_allowlist: null

  steps:
    - id: router
      action: call_model
      prompt_key: "e2e/router_v1"
      user_parts:
        user:
          source: user_query
          template: "### User:\\n{}\\n\\n"
      next: handle_router

    - id: handle_router
      action: prefix_router
      routes:
        bm25:
          prefix: "[BM25:]"
          next: search
      on_other: search

    - id: search
      action: search_nodes
      search_type: "bm25"
      next: expand

    - id: expand
      action: expand_dependency_tree
      max_depth_from_settings: "graph_max_depth"
      max_nodes_from_settings: "graph_max_nodes"
      edge_allowlist_from_settings: "graph_edge_allowlist"
      next: fetch_texts

    - id: fetch_texts
      action: fetch_node_texts
      next: call_answer

    - id: call_answer
      action: call_model
      prompt_key: "e2e/answer_v1"
      user_parts:
        evidence:
          source: context_blocks
          template: "### Evidence:\\n{}\\n\\n"
        user:
          source: user_query
          template: "### User:\\n{}\\n\\n"
      next: handle_answer

    - id: handle_answer
      action: prefix_router
      routes:
        answer:
          prefix: "[Answer:]"
          next: finalize
        requesting_data:
          prefix: "[Requesting data on:]"
          next: search
      on_other: finalize

    - id: finalize
      action: finalize
      end: true
"""

    yaml_path = tmp_path / "e2e_graph_search_expand_fetch.yaml"
    yaml_path.write_text(textwrap.dedent(yaml_text).strip(), encoding="utf-8")

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)

    # Ensure prompts exist and pipeline points to tmp prompts_dir.
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "e2e").mkdir(parents=True, exist_ok=True)
    (prompts_dir / "e2e" / "router_v1.txt").write_text("SYS ROUTER\n", encoding="utf-8")
    (prompts_dir / "e2e" / "answer_v1.txt").write_text("SYS ANSWER\n", encoding="utf-8")

    if pipe.settings is None:
        pipe.settings = {}
    pipe.settings["prompts_dir"] = str(prompts_dir)

    return pipe


def _runtime(*, pipe_settings: Dict[str, Any], model: Any, dispatcher: Any, graph: Any) -> PipelineRuntime:
    history_manager = HistoryManager(backend=InMemoryMockRedis(), session_id="s")

    backend = RetrievalBackendAdapter(
        dispatcher=dispatcher,
        graph_provider=graph,
        pipeline_settings=pipe_settings,
    )

    return PipelineRuntime(
        pipeline_settings=pipe_settings,
        model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=history_manager,
        logger=DummyInteractionLogger(),
        constants=constants,
        retrieval_backend=backend,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=graph,
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
        add_plant_link=lambda text, consultant=None: text,
    )


def test_e2e_graph_search_expand_fetch_followup_then_answer(tmp_path: Path) -> None:
    pipe = _load_pipeline(tmp_path)

    model = FakeModelWithAsk(
        outputs_by_consultant={
            "e2e_graph_search_expand_fetch": [
                "[BM25:] entry point",
                "[Requesting data on:] Program.cs Main",
                "[Answer:] E2E OK (after followup)",
            ],
        }
    )

    retriever = FakeRetriever(
        results=[
            {"Id": "A", "File": "a.cs", "Content": "class A {}"},
            {"Id": "B", "File": "b.cs", "Content": "class B {}"},
        ]
    )
    dispatcher = DummyRetrievalDispatcher(retriever=retriever)
    graph = FakeGraphProvider()

    rt = _runtime(pipe_settings=pipe.settings, model=model, dispatcher=dispatcher, graph=graph)

    engine = PipelineEngine(build_default_action_registry())

    state = PipelineState(
        user_query="Gdzie jest entry point?",
        session_id="s",
        consultant="e2e_graph_search_expand_fetch",
        repository="nopCommerce",
        branch="develop",
        translate_chat=True,
    )

    out = engine.run(pipe, state, rt)
    assert out.final_answer == "E2E OK (after followup)"
