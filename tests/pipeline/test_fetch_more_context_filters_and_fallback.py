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

    def add_iteration(self, meta, faiss_results):
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


def test_fetch_more_context_merges_branch_and_repo_filters():
    step = StepDef(
    id="fetch",
    action="fetch_more_context",
    raw={"id": "fetch", "action": "fetch_more_context"},
)

    retr = FakeRetriever(results=[{"path": "a.cs", "content": "x"}])
    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr, semantic_rerank=retr)

    rt = _runtime({"branch": "develop", "repository": "nopCommerce", "top_k": 2}, dispatcher)

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rej",
        branch="develop",
        translate_chat=False,
    )
    state.retrieval_mode = "bm25"
    state.retrieval_query = "Main entry point"
    state.retrieval_filters = {"data_type": "regular_code"}

    FetchMoreContextAction().execute(step, state, rt)

    assert retr.calls
    call = retr.calls[0]
    assert call["filters"]["branch"] == "develop"
    assert call["filters"]["repo"] == "nopCommerce"
    assert call["filters"]["data_type"] == "regular_code"
    assert len(state.context_blocks) == 1


def test_fetch_more_context_returns_gracefully_when_missing_dispatcher():
    step = StepDef(
    id="fetch",
    action="fetch_more_context",
    raw={"id": "fetch", "action": "fetch_more_context"},
)

    rt = PipelineRuntime(
        pipeline_settings={"top_k": 2},
        model=FakeModelClient(outputs=[""]),
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistory(),
        logger=DummyLogger(),
        constants=constants,
        retrieval_dispatcher=None,
        bm25_searcher=None,
        semantic_rerank_searcher=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rej",
        branch="develop",
        translate_chat=False,
    )
    state.retrieval_mode = "semantic"
    state.retrieval_query = "something"

    # Should not throw
    FetchMoreContextAction().execute(step, state, rt)
