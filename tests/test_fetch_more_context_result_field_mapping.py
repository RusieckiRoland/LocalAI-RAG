import constants

from code_query_engine.pipeline.actions.fetch_more_context import FetchMoreContextAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState
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


def _runtime(settings, dispatcher):
    return PipelineRuntime(
        pipeline_settings=settings,
        model=FakeModelClient(outputs=[""]),
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


def test_fetch_more_context_accepts_File_Content_keys_and_line_range():
    step = StepDef(
        id="fetch",
        action="fetch_more_context",
        raw={"id": "fetch", "action": "fetch_more_context"},
    )

    retr = FakeRetriever(
        results=[
            {
                "File": "src/a.cs",
                "Content": "HELLO",
                "start_line": 10,
                "end_line": 20,
            }
        ]
    )
    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr, semantic_rerank=retr)
    rt = _runtime({"top_k": 1}, dispatcher)

    state = PipelineState(
        user_query="Q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )
    state.retrieval_mode = "semantic"
    state.retrieval_query = "query"

    state.search_type = "semantic"

    FetchMoreContextAction().execute(step, state, rt)

    assert len(state.context_blocks) == 1
    block = state.context_blocks[0]

    # Must include file path + range + content
    assert "File: src/a.cs (lines 10-20)" in block
    assert "HELLO" in block
