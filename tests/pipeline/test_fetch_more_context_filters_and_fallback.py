import pytest

from code_query_engine.pipeline.actions.fetch_more_context import FetchMoreContextAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class DummyHistoryManager:
    def add_iteration(self, followup, faiss_results):
        return None


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class DummySearcher:
    def __init__(self):
        self.calls = []

    def search(self, query, top_k=5, *, filters=None, **kwargs):
        # Capture calls for assertions.
        self.calls.append({"query": query, "top_k": top_k, "filters": filters, "kwargs": dict(kwargs)})

        # Return at least one hit so compressor is invoked.
        return [
            {
                "File": "src/Some.cs",
                "Content": "public class OrderService { }",
                "Class": "OrderService",
                "Member": "PlaceOrder",
                "Score": 0.9,
            }
        ]


class DummyRuntime:
    def __init__(self, searcher):
        self.searcher = searcher
        self.history_manager = DummyHistoryManager()
        self.logger = DummyLogger()
        self.pipeline_settings = {}


def test_fetch_more_context_passes_query_without_scope_and_applies_hard_and_soft_filters(monkeypatch):
    """
    Expected behavior:
    - Query passed to searcher must NOT contain the 'CS |' part.
    - Filters must include:
        - hard branch filter from UI/state
        - soft data_type filter from router scope
    - If first compression yields too little context, fallback relaxes ONLY soft filters (keeps branch).
    """
    # Patch compressor to force fallback on first attempt.
    # First call -> "", second call -> "OK"
    calls = {"n": 0}

    def fake_compress_chunks(*args, **kwargs):
        calls["n"] += 1
        return "" if calls["n"] == 1 else "OK"

    monkeypatch.setattr("dotnet_sumarizer.code_compressor.compress_chunks", fake_compress_chunks)

    searcher = DummySearcher()
    runtime = DummyRuntime(searcher)

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    # Simulate "already parsed" router output:
    state.retrieval_mode = "semantic_rerank"
    state.retrieval_query = "order creation call chain"
    state.retrieval_filters = {"data_type": ["regular_code"]}

    step = StepDef(id="fetch_more_context", action="fetch_more_context", raw={"id": "fetch_more_context", "action": "fetch_more_context"})
    action = FetchMoreContextAction()

    _ = action.execute(step, state, runtime)

    assert len(searcher.calls) == 2, "Expected 2 searches: initial + fallback (relaxed soft filters)."

    first = searcher.calls[0]
    second = searcher.calls[1]

    assert first["query"] == "order creation call chain"
    assert first["filters"] == {"branch": ["develop"], "data_type": ["regular_code"]}

    assert second["query"] == "order creation call chain"
    # Fallback must keep branch (hard) and drop data_type (soft)
    assert second["filters"] == {"branch": ["develop"]}

    # Context must be appended when fallback succeeded.
    assert state.context_blocks, "Expected context_blocks to have at least one block."
    assert state.context_blocks[-1] == "OK"


def test_fetch_more_context_any_scope_should_keep_branch_and_allow_both_types(monkeypatch):
    """
    When router scope is ANY (regular_code + db_code), we pass that as soft filter.
    Implementation may still do a fallback search if the compressed context is too short,
    so we assert the first call uses the correct filters and branch is always preserved.
    """
    # Make compression "long enough" to avoid fallback if you want deterministic 1 call,
    # but keep assertions robust even if fallback happens.
    monkeypatch.setattr("dotnet_sumarizer.code_compressor.compress_chunks", lambda *a, **k: "X" * 500)

    searcher = DummySearcher()
    runtime = DummyRuntime(searcher)

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    state.retrieval_mode = "semantic_rerank"
    state.retrieval_query = "checkout confirm order"
    state.retrieval_filters = {"data_type": ["regular_code", "db_code"]}

    step = StepDef(id="fetch_more_context", action="fetch_more_context", raw={"id": "fetch_more_context", "action": "fetch_more_context"})
    action = FetchMoreContextAction()

    _ = action.execute(step, state, runtime)

    assert len(searcher.calls) >= 1

    # First call must include hard branch + ANY soft filter
    first = searcher.calls[0]
    assert first["query"] == "checkout confirm order"
    assert first["filters"] == {"branch": ["develop"], "data_type": ["regular_code", "db_code"]}

    # Any additional calls (fallback) must still keep the branch hard filter
    for c in searcher.calls[1:]:
        assert c["filters"] == {"branch": ["develop"]}
