import pytest

import constants
from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator
from code_query_engine.pipeline.providers.fakes import FakeModelClient, FakeRetriever
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher


class DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class DummyMarkdownTranslator:
    def translate(self, markdown_en: str) -> str:
        return markdown_en


class DummyHistory:
    def get_context_blocks(self):
        return []

    def add_iteration(self, followup, faiss_results):
        return None

    def set_final_answer(self, answer_en, answer_pl):
        return None


class DummyLogger:
    def log_interaction(self, **kwargs):
        return None


def test_engine_smoke_runs_to_end(tmp_path):
    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
        """
YAMLpipeline:
  name: smoke

  settings:
    entry_step_id: call_model

  steps:
    - id: call_model
      action: call_model
      prompt_key: "rejewski_router_v1"
      next: finalize

    - id: finalize
      action: finalize
      end: true
""".strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)

    model = FakeModelClient(outputs=["[DIRECT:]"])
    dispatcher = RetrievalDispatcher(semantic=FakeRetriever(results=[]))

    rt = PipelineRuntime(
        pipeline_settings=pipe.settings,
        model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistory(),
        logger=DummyLogger(),
        constants=constants,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    engine = PipelineEngine(build_default_action_registry())
    state = PipelineState(
        user_query="hi",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )
    out = engine.run(pipe, state, rt)
    assert out.steps_used >= 1
