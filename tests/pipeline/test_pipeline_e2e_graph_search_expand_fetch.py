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
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter


class DummyTranslator:
    def translate(self, text: str) -> str:
        # minimal PL->EN stub
        return f"EN: {text}"


class DummyMarkdownTranslator:
    def translate(self, markdown_en: str) -> str:
        # minimal EN->PL stub
        return f"PL: {markdown_en}"


class DummyLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error(self, *args: Any, **kwargs: Any) -> None:
        pass


class FakeModelWithAsk:
    """
    Minimal model stub aligned with CURRENT production Model.ask contract.
    """

    def __init__(self, *, outputs_by_consultant: Dict[str, List[str]]) -> None:
        self._outputs_by_consultant = {k: list(v) for k, v in (outputs_by_consultant or {}).items()}
        self.calls: List[Dict[str, str]] = []

    def ask(
        self,
        *,
        prompt: str | None = None,
        system_prompt: str | None = None,
        consultant: str | None = None,
        context: str | None = None,
        question: str | None = None,
        **kwargs: Any,
    ) -> str:
        # Normalize old call shapes into "prompt"
        if prompt is None:
            ctx = context or ""
            q = question or ""
            prompt = (ctx + "\n" + q).strip()

        chosen_consultant = (consultant or "").strip()

        self.calls.append(
            {
                "consultant": chosen_consultant,
                "system_prompt": system_prompt or "",
                "prompt": prompt or "",
                "context": context or "",
                "question": question or "",
            }
        )

        # Output queue selection
        if chosen_consultant and chosen_consultant in self._outputs_by_consultant:
            q = self._outputs_by_consultant[chosen_consultant]
        elif len(self._outputs_by_consultant) == 1:
            only_key = next(iter(self._outputs_by_consultant.keys()))
            q = self._outputs_by_consultant[only_key]
        else:
            q = []

        if not q:
            return ""
        return q.pop(0)

    def ask_chat(
        self,
        *,
        prompt: str,
        history: Any = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        return self.ask(prompt=prompt, system_prompt=system_prompt, **kwargs)


class FakeRetriever:
    def __init__(self, *, results: List[Dict[str, Any]]) -> None:
        self.results = list(results or [])
        self.calls: List[Dict[str, Any]] = []

    def search(self, *, query: str, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "top_k": top_k, "settings": dict(settings or {}), "filters": dict(filters or {})})
        return list(self.results)


class DummyRetrievalDispatcher:
    def __init__(self, *, retriever: FakeRetriever) -> None:
        self._retriever = retriever

    def search(self, decision: Any, *, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = getattr(decision, "query", None) or ""
        return self._retriever.search(query=str(query), top_k=int(top_k), settings=settings, filters=filters)


class FakeGraphProvider:
    def __init__(self) -> None:
        self.expand_calls: List[Dict[str, Any]] = []
        self.fetch_calls: List[Dict[str, Any]] = []

    def expand_dependency_tree(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.expand_calls.append({"args": args, "kwargs": kwargs})
        return {"nodes": ["A", "B"], "edges": [{"from": "A", "to": "B", "type": "Calls"}]}

    def fetch_node_texts(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        self.fetch_calls.append({"args": args, "kwargs": kwargs})
        return [
            {"id": "A", "text": "class A {}"},
            {"id": "B", "text": "class B {}"},
        ]


class DummyInteractionLogger:
    def log_interaction(self, *args: Any, **kwargs: Any) -> None:
        return


def _pipelines_root() -> Path:
    return Path(__file__).resolve().parents[1] / "e2e" / "data" / "pipelines"


def _load_pipeline() -> Any:
    loader = PipelineLoader(pipelines_root=str(_pipelines_root()))
    pipe = loader.load_by_name("e2e_graph_search_expand_fetch")
    PipelineValidator().validate(pipe)
    return pipe


def _runtime(*, pipe_settings: Dict[str, Any], model: FakeModelWithAsk, dispatcher: DummyRetrievalDispatcher, graph: FakeGraphProvider) -> PipelineRuntime:
    backend = RetrievalBackendAdapter(dispatcher=dispatcher, graph_provider=graph, pipeline_settings=pipe_settings)
    return PipelineRuntime(
        pipeline_settings=pipe_settings,
        model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=None,
        logger=DummyInteractionLogger(),
        constants=constants,
        retrieval_backend=backend,
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
