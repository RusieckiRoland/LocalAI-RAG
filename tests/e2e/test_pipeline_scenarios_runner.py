import json
import textwrap
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pytest

from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator

from history.history_manager import HistoryManager


# -----------------------
# Test doubles
# -----------------------

class DummyMarkdownTranslator:
    def translate_en_pl(self, text: str) -> str:
        return text


class DummyTranslator:
    def translate_pl_en(self, text: str) -> str:
        return text


class NoopInteractionLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        return

    def debug(self, *args: Any, **kwargs: Any) -> None:
        return

    def warning(self, *args: Any, **kwargs: Any) -> None:
        return

    def error(self, *args: Any, **kwargs: Any) -> None:
        return


class FakeModelWithAsk:
    def __init__(self, outputs_by_consultant: Dict[str, List[str]]):
        self._outputs_by_consultant = outputs_by_consultant
        self._counters: Dict[str, int] = {}

    def ask(self, *, consultant: str, prompt: str, **kwargs: Any) -> str:
        outs = self._outputs_by_consultant.get(consultant, [])
        idx = self._counters.get(consultant, 0)
        self._counters[consultant] = idx + 1
        if idx >= len(outs):
            return ""
        return outs[idx]


class FakeRetriever:
    def __init__(self, results: List[Dict[str, Any]]):
        self._results = results

    def search(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return self._results


class DummyRetrievalDispatcher:
    def __init__(self, retriever: Any):
        self._retriever = retriever

    def retrieve(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return self._retriever.search(*args, **kwargs)


class FakeGraphProvider:
    def __init__(self, *, expand_result: Dict[str, Any], node_texts: List[Dict[str, Any]]):
        self._expand_result = expand_result
        self._node_texts = node_texts

    def expand(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._expand_result

    def fetch_node_texts(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return self._node_texts


class InMemoryMockRedis:
    def __init__(self):
        self._store: Dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
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


def _pipelines_root() -> Path:
    return Path(__file__).parent / "data" / "pipelines"


def _load_pipeline_from_file(pipeline_file: str, pipeline_name: str) -> Any:
    pipelines_root = _pipelines_root()
    yaml_path = pipelines_root / pipeline_file
    loader = PipelineLoader(pipelines_root=pipelines_root)
    return loader.load_from_path(str(yaml_path), pipeline_name=pipeline_name)


def _load_pipeline_from_inline_yaml(yaml_text: str) -> Any:
    # Inline YAML scenarios are standalone; write them to a temp file and load.
    with tempfile.TemporaryDirectory() as td:
        tmp_root = Path(td)
        yaml_path = tmp_root / "inline.yaml"
        yaml_path.write_text(textwrap.dedent(yaml_text).lstrip(), encoding="utf-8")

        loader = PipelineLoader(pipelines_root=tmp_root)
        return loader.load_from_path(str(yaml_path), pipeline_name=None)


def _runtime(*, pipe_settings: Dict[str, Any], model: Any, dispatcher: Any, graph: Any) -> PipelineRuntime:
    history = HistoryManager(backend=InMemoryMockRedis(), session_id="s")

    # 'constants' is a project-level module in your repo; the test uses it via runtime.
    import constants  # type: ignore

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
    raw = next(s for s in data["scenarios"] if s["name"] == scenario_name)

    mode = str(raw.get("mode") or "run").strip().lower()

    # -----------------------
    # validate_only: load inline YAML and assert it fails with expected message
    # -----------------------
    if mode == "validate_only":
        yaml_text = raw.get("pipeline_yaml")
        assert isinstance(yaml_text, str) and yaml_text.strip(), "validate_only scenario must provide pipeline_yaml"

        expected_err = (raw.get("expected", {}) or {}).get("error_contains", "")
        expected_err = str(expected_err or "").strip()

        with pytest.raises(Exception) as ex:
            pipe = _load_pipeline_from_inline_yaml(yaml_text)
            PipelineValidator().validate(pipe)

        if expected_err:
            assert expected_err in str(ex.value)
        return

    # -----------------------
    # lint_only: load pipeline from shared multi-pipeline file and assert warnings
    # -----------------------
    if mode == "lint_only":
        pipeline_name = str(raw.get("pipeline_name") or "").strip()
        assert pipeline_name, "lint_only scenario must provide pipeline_name"

        pipe = _load_pipeline_from_file(data["pipeline_file"], pipeline_name=pipeline_name)
        warnings = PipelineValidator().validate(pipe)

        expected_warns = (raw.get("expected", {}) or {}).get("warnings_contains", []) or []
        joined = "\n".join(warnings)

        for w in expected_warns:
            w = str(w or "").strip()
            if w:
                assert w in joined

        return

    # -----------------------
    # run: execute pipeline and assert final output
    # -----------------------
    pipeline_name = str(raw.get("pipeline_name") or "").strip()
    assert pipeline_name, "run scenario must provide pipeline_name"

    pipe = _load_pipeline_from_file(data["pipeline_file"], pipeline_name=pipeline_name)

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

    # Safety: some actions use a loop counter; ensure it exists for older state versions.
    if not hasattr(state, "turn_loop_counter"):
        setattr(state, "turn_loop_counter", 0)

    out = engine.run(pipe, state, rt)

    must_contain = (sc.expected.get("final_answer_contains") or "").strip()
    if must_contain:
        assert must_contain in (out.final_answer or "")
