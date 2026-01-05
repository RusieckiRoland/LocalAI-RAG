import textwrap

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
    def __init__(self):
        self._blocks = []

    def get_context_blocks(self):
        return list(self._blocks)

    def add_iteration(self, followup, faiss_results):
        return None

    def set_final_answer(self, answer_en, answer_pl):
        return None


class DummyLogger:
    def log_interaction(self, **kwargs):
        return None


def test_pipeline_router_bm25_fetch_then_answer(tmp_path):
    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            YAMLpipeline:
              name: e2e

              settings:
                entry_step_id: call_router
                top_k: 2

              steps:
                - id: call_router
                  action: call_model
                  prompt_key: "rejewski_router_v1"
                  next: handle_router

                - id: handle_router
                  action: handle_prefix
                  bm25_prefix: "[BM25:]"
                  semantic_prefix: "[SEMANTIC:]"
                  hybrid_prefix: "[HYBRID:]"
                  semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
                  direct_prefix: "[DIRECT:]"
                  on_bm25: fetch
                  on_semantic: fetch
                  on_hybrid: fetch
                  on_semantic_rerank: fetch
                  on_direct: finalize
                  on_other: finalize
                  next: finalize

                - id: fetch
                  action: fetch_more_context
                  next: call_answer

                - id: call_answer
                  action: call_model
                  prompt_key: "rejewski_answer_v1"
                  next: handle_answer

                - id: handle_answer
                  action: handle_prefix
                  answer_prefix: "[Answer:]"
                  followup_prefix: "[Requesting data on:]"
                  on_answer: finalize
                  on_other: finalize

                - id: finalize
                  action: finalize
                  end: true
            """
        ).strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)

    model = FakeModelClient(
    outputs_by_consultant={
        "rejewski": [
            "[BM25:] CS | Program.cs Main entry point",
            "[Answer:] The entry point is Program.Main",
        ],
    }
    )


    retr = FakeRetriever(
        results=[
            {"path": "src/App/Program.cs", "content": "static void Main() {}", "start_line": 1, "end_line": 1}
        ]
    )

    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr, semantic_rerank=retr)

    rt = PipelineRuntime(
        pipeline_settings=pipe.settings,
        main_model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistory(),
        logger=DummyLogger(),
        constants=constants,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=retr,
        semantic_rerank_searcher=retr,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    engine = PipelineEngine(build_default_action_registry())
    state = PipelineState(
        user_query="Where is the entry point?",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = engine.run(pipe, state, rt)
    assert out.answer_en is not None
    assert "Program.Main" in out.answer_en
