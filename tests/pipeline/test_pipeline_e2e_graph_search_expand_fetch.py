from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import textwrap

import constants

from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator


class DummyTranslator:
    def translate(self, text: str) -> str:
        # minimal PL->EN stub
        return f"EN: {text}"


class DummyMarkdownTranslator:
    def translate_markdown(self, text: str) -> str:
        # minimal EN->PL stub
        return f"PL: {text}"


class DummyLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error(self, *args: Any, **kwargs: Any) -> None:
        pass


class FakeModelWithAsk:
    """
    Minimal model stub that matches CallModelAction expectations.

    The production code historically used different call shapes:
      - ask(context=..., question=..., consultant=...)
      - ask(prompt=..., consultant=...)
    This test double supports both to stay aligned with the current pipeline.
    """

    def __init__(self, *, outputs_by_consultant: Dict[str, List[str]]) -> None:
        self._outputs_by_consultant = {k: list(v) for k, v in (outputs_by_consultant or {}).items()}
        self.calls: List[Dict[str, str]] = []

    def ask(
        self,
        *,
        consultant: str,
        prompt: str | None = None,
        context: str | None = None,
        question: str | None = None,
        **kwargs: Any,
    ) -> str:
        self.calls.append(
            {
                "consultant": consultant,
                "prompt": prompt or "",
                "context": context or "",
                "question": question or "",
            }
        )
        q = self._outputs_by_consultant.get(consultant, [])
        if not q:
            return ""
        return q.pop(0)


class FakeRetriever:
    def __init__(self, *, results: List[Dict[str, Any]]) -> None:
        self.results = list(results or [])
        self.calls: List[Dict[str, Any]] = []

    def search(self, *, query: str, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "top_k": top_k, "settings": dict(settings or {}), "filters": dict(filters or {})})
        return list(self.results)


@dataclass
class RetrievalDecision:
    mode: str
    query: str


class DummyInteractionLogger:
    def log_interaction(self, *args, **kwargs) -> None:
        return None


class DummyRetrievalDispatcher:
    def __init__(self, *, retriever: FakeRetriever) -> None:
        self._retriever = retriever

    def search(self, decision: RetrievalDecision, *, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._retriever.search(query=decision.query, top_k=top_k, settings=settings, filters=filters)


class FakeGraphProvider:
    def __init__(self) -> None:
        self.expand_calls: List[Dict[str, Any]] = []
        self.fetch_calls: List[Dict[str, Any]] = []

    def expand_dependency_tree(
        self,
        *,
        seed_nodes: List[str],
        max_depth: int = 2,
        max_nodes: int = 200,
        edge_allowlist: Optional[List[str]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        active_index: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.expand_calls.append(
            {
                "seed_nodes": list(seed_nodes),
                "max_depth": max_depth,
                "max_nodes": max_nodes,
                "edge_allowlist": list(edge_allowlist or []),
                "repository": repository,
                "branch": branch,
                "active_index": active_index,
            }
        )

        # deterministic fake graph
        nodes = []
        edges = []
        for s in seed_nodes:
            nodes.append(s)
        if seed_nodes:
            nodes.append("C")
            edges.append({"from": seed_nodes[0], "to": "C", "type": "dep"})
        return {"nodes": nodes, "edges": edges}

    def fetch_node_texts(
        self,
        *,
        node_ids: List[str],
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        active_index: Optional[str] = None,
        max_chars: int = 50_000,
    ) -> List[Dict[str, Any]]:
        self.fetch_calls.append(
            {
                "node_ids": list(node_ids),
                "repository": repository,
                "branch": branch,
                "active_index": active_index,
                "max_chars": max_chars,
            }
        )
        out: List[Dict[str, Any]] = []
        used = 0
        for nid in node_ids:
            txt = f"[NODE {nid}] text"
            if used + len(txt) > max_chars:
                txt = txt[: max(0, max_chars - used)]
            used += len(txt)
            out.append({"id": nid, "text": txt})
            if used >= max_chars:
                break
        return out


def _pipelines_root() -> Path:
    # tests/e2e/data/pipelines
    return Path(__file__).resolve().parents[1] / "e2e" / "data" / "pipelines"


def _load_pipeline() -> Any:
    loader = PipelineLoader(pipelines_root=str(_pipelines_root()))
    pipe = loader.load_by_name("e2e_graph_search_expand_fetch")
    PipelineValidator().validate(pipe)
    return pipe


def _runtime(*, pipe_settings: Dict[str, Any], model: FakeModelWithAsk, dispatcher: DummyRetrievalDispatcher, graph: FakeGraphProvider) -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings=pipe_settings,
        main_model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=None,
        logger=DummyInteractionLogger(),
        constants=constants,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=graph,
        token_counter=None,
        add_plant_link=lambda x, consultant=None: x,
    )


def test_e2e_graph_search_expand_fetch_followup_then_answer() -> None:
    pipe = _load_pipeline()

    model = FakeModelWithAsk(
        outputs_by_consultant={
            "e2e_graph_search_expand_fetch": [
                "[BM25:] entry point",
                "[Requesting data on:] Program.cs Main",
                f"[Answer:] E2E OK (after followup)",
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
        branch="develop",
        translate_chat=True,
    )

    out = engine.run(pipe, state, rt)

    assert out.final_answer
    assert "E2E OK" in out.final_answer

    # followup => search should have happened at least twice (first + after followup)
    assert len(retriever.calls) >= 2

    # graph expansion and node texts should be used
    assert graph.expand_calls
    assert graph.fetch_calls


def test_e2e_graph_search_expand_fetch_direct_answer() -> None:
    pipe = _load_pipeline()

    model = FakeModelWithAsk(
        outputs_by_consultant={
            "e2e_graph_search_expand_fetch": [
                "[DIRECT:]",
                f"[Answer:] E2E OK (direct)",
            ],
        }
    )

    retriever = FakeRetriever(results=[{"Id": "A", "File": "a.cs", "Content": "class A {}"}])
    dispatcher = DummyRetrievalDispatcher(retriever=retriever)
    graph = FakeGraphProvider()

    rt = _runtime(pipe_settings=pipe.settings, model=model, dispatcher=dispatcher, graph=graph)

    engine = PipelineEngine(build_default_action_registry())

    state = PipelineState(
        user_query="Gdzie jest entry point?",
        session_id="s",
        consultant="e2e_graph_search_expand_fetch",
        branch="develop",
        translate_chat=True,
    )

    out = engine.run(pipe, state, rt)

    assert out.final_answer
    assert "E2E OK (direct)" in out.final_answer

    # direct path => no retrieval / no graph
    assert len(retriever.calls) == 0
    assert len(graph.expand_calls) == 0
    assert len(graph.fetch_calls) == 0
