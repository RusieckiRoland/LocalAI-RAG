from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import constants
from history.history_manager import HistoryManager
from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator


# -----------------------
# Fakes (self-contained)
# -----------------------

class FakeModelWithAsk:
    def __init__(self, *, outputs_by_consultant: Dict[str, List[str]]) -> None:
        self._by = {k: list(v) for k, v in (outputs_by_consultant or {}).items()}
        self.calls: List[Dict[str, Any]] = []

    def ask(self, *, context: str, question: str, consultant: str) -> str:
        self.calls.append({"consultant": consultant, "question": question, "context": context})
        seq = self._by.get(consultant, [])
        if not seq:
            return ""
        return seq.pop(0)


class FakeRetriever:
    def __init__(self, *, results: List[Dict[str, Any]]) -> None:
        self._results = list(results or [])
        self.calls: List[Dict[str, Any]] = []

    def search(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        self.calls.append({"args": args, "kwargs": kwargs})
        return list(self._results)


class DummyRetrievalDispatcher:
    def __init__(self, *, retriever: FakeRetriever) -> None:
        self._retriever = retriever

    def search(self, decision: Any, *, top_k: int, settings: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        # FetchMoreContextAction normalizuje różne formaty wyników.
        # Tu tylko delegujemy do jednego fake retrievera.
        return self._retriever.search(decision=decision, top_k=top_k, settings=settings, filters=filters)


class FakeGraphProvider:
    def __init__(self, *, expand_result: Dict[str, Any], node_texts: List[Dict[str, Any]]) -> None:
        self._expand = dict(expand_result or {"nodes": [], "edges": []})
        self._texts = list(node_texts or [])
        self.expand_calls: List[Dict[str, Any]] = []
        self.text_calls: List[Dict[str, Any]] = []

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
        return dict(self._expand)

    def fetch_node_texts(
        self,
        *,
        node_ids: List[str],
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        active_index: Optional[str] = None,
        max_chars: int = 50_000,
    ) -> List[Dict[str, Any]]:
        self.text_calls.append(
            {
                "node_ids": list(node_ids),
                "repository": repository,
                "branch": branch,
                "active_index": active_index,
                "max_chars": max_chars,
            }
        )
        return list(self._texts)


class DummyTranslator:
    def translate(self, text: str) -> str:
        # PL -> EN (stub)
        return f"EN: {text}"


class DummyMarkdownTranslator:
    def translate(self, text: str) -> str:
        # EN -> PL (stub)
        return f"PL: {text}"

    def translate_markdown(self, text: str) -> str:
        # jeśli akcja używa innej nazwy metody
        return f"PL: {text}"


class NoopInteractionLogger:
    def log_interaction(self, **kwargs: Any) -> None:
        return


class InMemoryMockRedis:
    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


# -----------------------
# Scenario loader
# -----------------------

@dataclass(frozen=True)
class Scenario:
    name: str
    user_query: str
    translate_chat: bool
    model_outputs: Dict[str, List[str]]
    retriever_results: List[Dict[str, Any]]
    graph_expand_result: Dict[str, Any]
    graph_node_texts: List[Dict[str, Any]]
    expected: Dict[str, Any]


def _load_scenarios() -> Dict[str, Any]:
    root = Path(__file__).resolve().parent
    p = root / "scenarios" / "pipeline_scenarios.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _load_pipeline(pipeline_file: str):
    pipelines_root = Path(__file__).resolve().parent / "data" / "pipelines"
    yaml_path = pipelines_root / pipeline_file

    loader = PipelineLoader(pipelines_root=str(pipelines_root))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)
    return pipe


def _runtime(*, pipe_settings: Dict[str, Any], model: Any, dispatcher: Any, graph: Any) -> PipelineRuntime:
    history = HistoryManager(backend=InMemoryMockRedis(), session_id="s")

    return PipelineRuntime(
        pipeline_settings=pipe_settings,
        main_model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=history,
        logger=NoopInteractionLogger(),
        constants=constants,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=graph,
        token_counter=None,
        add_plant_link=lambda x: x,
    )


def _scenario_ids() -> List[str]:
    data = _load_scenarios()
    return [s["name"] for s in data.get("scenarios", [])]


@pytest.mark.parametrize("scenario_name", _scenario_ids())
def test_pipeline_scenarios_runner(scenario_name: str) -> None:
    data = _load_scenarios()
    pipe = _load_pipeline(data["pipeline_file"])

    raw = next(s for s in data["scenarios"] if s["name"] == scenario_name)
    sc = Scenario(
        name=raw["name"],
        user_query=raw["user_query"],
        translate_chat=bool(raw.get("translate_chat", False)),
        model_outputs=raw.get("model_outputs", {}),
        retriever_results=raw.get("retriever_results", []),
        graph_expand_result=raw.get("graph_expand_result", {"nodes": [], "edges": []}),
        graph_node_texts=raw.get("graph_node_texts", []),
        expected=raw.get("expected", {}),
    )

    model = FakeModelWithAsk(outputs_by_consultant=sc.model_outputs)
    retriever = FakeRetriever(results=sc.retriever_results)
    dispatcher = DummyRetrievalDispatcher(retriever=retriever)
    graph = FakeGraphProvider(expand_result=sc.graph_expand_result, node_texts=sc.graph_node_texts)

    rt = _runtime(pipe_settings=pipe.settings, model=model, dispatcher=dispatcher, graph=graph)

    engine = PipelineEngine(build_default_action_registry())

    state = PipelineState(
        user_query=sc.user_query,
        session_id="s",
        consultant="e2e_scenarios_runner",
        branch="develop",
        translate_chat=sc.translate_chat,
    )

    # Safety: część akcji używa licznika pętli (jeśli nie istnieje w dataclass)
    if not hasattr(state, "turn_loop_counter"):
        setattr(state, "turn_loop_counter", 0)

    out = engine.run(pipe, state, rt)

    must_contain = (sc.expected.get("final_answer_contains") or "").strip()
    if must_contain:
        assert must_contain in (out.final_answer or "")

    allowed_qt = sc.expected.get("query_type_in")
    if isinstance(allowed_qt, list) and allowed_qt:
        assert (out.query_type or "") in allowed_qt
