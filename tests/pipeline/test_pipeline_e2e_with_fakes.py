import textwrap

import constants
from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator
from code_query_engine.pipeline.providers.fakes import FakeRetriever
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.providers.retrieval_backend_adapter import RetrievalBackendAdapter


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
    # Test-only prompts dir (do NOT use production prompts/)
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # call_model loads <prompts_dir>/<prompt_key>.txt
    (prompts_dir / "rejewski_router_v1.txt").write_text("SYS ROUTER\n", encoding="utf-8")
    (prompts_dir / "rejewski_answer_v1.txt").write_text("SYS ANSWER\n", encoding="utf-8")

    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
    textwrap.dedent(
        f"""
        YAMLpipeline:
          name: e2e

          settings:
            entry_step_id: call_router
            repository: "nopCommerce"
            top_k: 2
            prompts_dir: "{str(prompts_dir)}"

          steps:
            - id: call_router
              action: call_model
              prompt_key: "rejewski_router_v1"
              user_parts:
                user_question:
                  source: user_query
                  template: "### User:\\n{{}}\\n"
              next: handle_router

            - id: handle_router
              action: prefix_router
              routes:
                bm25:
                  prefix: "[BM25:]"
                  next: fetch_bm25
                semantic:
                  prefix: "[SEMANTIC:]"
                  next: fetch_semantic
                hybrid:
                  prefix: "[HYBRID:]"
                  next: fetch_hybrid
                semantic_rerank:
                  prefix: "[SEMANTIC_RERANK:]"
                  next: fetch_semantic_rerank
                direct:
                  prefix: "[DIRECT:]"
                  next: finalize
              on_other: finalize

            - id: fetch_bm25
              action: search_nodes
              search_type: bm25
              next: call_answer

            - id: fetch_semantic
              action: search_nodes
              search_type: semantic
              next: call_answer

            - id: fetch_hybrid
              action: search_nodes
              search_type: hybrid
              next: call_answer

            - id: fetch_semantic_rerank
              action: search_nodes
              search_type: semantic_rerank
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "rejewski_answer_v1"
              user_parts:
                evidence:
                  source: context_blocks
                  template: "### Evidence:\\n{{}}\\n"
                user_question:
                  source: user_query
                  template: "### User:\\n{{}}\\n"
              next: handle_answer

            - id: handle_answer
              action: prefix_router
              routes:
                answer:
                  prefix: "[Answer:]"
                  next: finalize
                followup:
                  prefix: "[Requesting data on:]"
                  next: finalize
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

    # Minimal model stub compatible with current call_model implementation
    class _PromptModel:
        def __init__(self, outputs):
            self._outputs = list(outputs)
            self.calls = []

        def ask(self, *, prompt: str, system_prompt=None, **kwargs):
            self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "kwargs": kwargs})
            return self._outputs.pop(0) if self._outputs else ""

    model = _PromptModel(
        outputs=[
            "[BM25:] CS | Program.cs Main entry point",
            "[Answer:] The entry point is Program.Main",
        ]
    )

    retr = FakeRetriever(
        results=[
            {"path": "src/App/Program.cs", "content": "static void Main() {}", "start_line": 1, "end_line": 1}
        ]
    )

    dispatcher = RetrievalDispatcher(bm25=retr)

    backend = RetrievalBackendAdapter(dispatcher=dispatcher, graph_provider=None, pipeline_settings=pipe.settings)

    rt = PipelineRuntime(
        pipeline_settings=pipe.settings,
        model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistory(),
        logger=DummyLogger(),
        constants=constants,
        retrieval_backend=backend,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
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
