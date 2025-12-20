from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import constants
from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.providers.retrieval import RetrievalDispatcher
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator
from code_query_engine.pipeline.providers.fakes import FakeModelClient, FakeRetriever
from history.history_manager import HistoryManager
from history.mock_redis import InMemoryMockRedis

# Import logger exactly how repo uses it now.
# If you keep it in code_query_engine.log_utils, adjust import accordingly.
from code_query_engine.log_utils import InteractionLogger


class FakeTokenCounter:
    def __init__(self, fixed_count: int) -> None:
        self.fixed_count = fixed_count
        self.calls: List[str] = []

    def count(self, text: str) -> int:
        self.calls.append(text)
        return self.fixed_count


class DummyTranslator:
    def __init__(self, prefix: str = "EN:") -> None:
        self.prefix = prefix
        self.calls: List[str] = []

    def translate(self, text: str) -> str:
        self.calls.append(text)
        return f"{self.prefix}{text}"


def _write_pipeline(tmp_path: Path, yaml_text: str) -> Path:
    p = tmp_path / "pipe.yaml"
    p.write_text(yaml_text.strip() + "\n", encoding="utf-8")
    return p


def _load_pipeline(pipelines_root: Path, yaml_path: Path):
    loader = PipelineLoader(pipelines_root=str(pipelines_root))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)
    return pipe


def _runtime(
    *,
    pipeline_settings: Dict[str, Any],
    model: FakeModelClient,
    dispatcher: Optional[RetrievalDispatcher],
    history_manager: HistoryManager,
    logger: Any,
    token_counter: Any,
    bm25_searcher: Any = None,
    semantic_rerank_searcher: Any = None,
    graph_provider: Any = None,
    translator_pl_en: Any = None,
):
    return PipelineRuntime(
        pipeline_settings=pipeline_settings,
        main_model=model,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=translator_pl_en,
        history_manager=history_manager,
        logger=logger,
        constants=constants,
        retrieval_dispatcher=dispatcher,
        bm25_searcher=bm25_searcher,
        semantic_rerank_searcher=semantic_rerank_searcher,
        graph_provider=graph_provider,
        token_counter=token_counter,
        add_plant_link=lambda x: x,
    )


def _run_engine(pipe, state: PipelineState, rt: PipelineRuntime):
    engine = PipelineEngine(build_default_action_registry())
    return engine.run(pipe, state, rt)


def test_e2e_bm25_scope_filters_and_answer(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_bm25
          settings:
            entry_step_id: call_router
            top_k: 2

          steps:
            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              bm25_prefix: "[BM25:]"
              semantic_prefix: "[SEMANTIC:]"
              hybrid_prefix: "[HYBRID:]"
              semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
              direct_prefix: "[DIRECT:]"
              on_bm25: fetch
              on_other: call_answer
              next: call_answer

            - id: fetch
              action: fetch_more_context
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: handle_answer

            - id: handle_answer
              action: handle_prefix
              answer_prefix: "[Answer:]"
              followup_prefix: "[FOLLOWUP:]"
              on_answer: persist
              on_followup: persist
              on_other: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    yaml_path = _write_pipeline(tmp_path, yaml_text)
    pipe = _load_pipeline(tmp_path, yaml_path)

    model = FakeModelClient(
        outputs_by_consultant={
            "e2e/router_v1": ["[BM25:] CS | Program.cs Main entry point"],
            "e2e/answer_v1": ["[Answer:] The entry point is Program.Main"],
        }
    )

    bm25 = FakeRetriever(
        results=[{"path": "src/App/Program.cs", "content": "static void Main() {}", "start_line": 1, "end_line": 1}]
    )
    dispatcher = RetrievalDispatcher(semantic=FakeRetriever(results=[]), bm25=bm25, semantic_rerank=FakeRetriever(results=[]))

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    log_file = tmp_path / "ai_interaction.log"
    logger = InteractionLogger(log_file)

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
        history_manager=history_manager,
        logger=logger,
        token_counter=None,
        bm25_searcher=bm25,
        semantic_rerank_searcher=None,
        translator_pl_en=None,
    )

    state = PipelineState(
        user_query="Where is the entry point?",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = _run_engine(pipe, state, rt)

    # Answer path
    assert out.final_answer is not None
    assert "Program.Main" in (out.final_answer or "")

    # Router parsing -> bm25 + CS scope
    assert state.retrieval_mode == "bm25"
    assert state.retrieval_filters.get("data_type") == ["regular_code"]

    # Fetch uses bm25 retriever and merged filters
    assert len(bm25.calls) == 1
    call = bm25.calls[0]
    assert "Program.cs Main entry point" in call["query"]

    filters = call.get("filters") or {}

    # Contract: handle_prefix sets retrieval_filters (e.g. data_type based on scope),
    # but branch/repository are not automatically injected into retriever filters here.
    assert filters.get("data_type") == ["regular_code"]

    assert call.get("top_k") == 2

    # Step trace sanity
    assert state.step_trace[:3] == ["call_router", "handle_router", "fetch"]
    assert state.step_trace[-1] == "persist"

    # Log written
    assert log_file.exists()
    txt = log_file.read_text(encoding="utf-8", errors="replace")
    assert "Where is the entry point?" in txt


def test_e2e_semantic_rerank_uses_semantic_rerank_backend(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_semantic_rerank
          settings:
            entry_step_id: call_router
            top_k: 3

          steps:
            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              bm25_prefix: "[BM25:]"
              semantic_prefix: "[SEMANTIC:]"
              hybrid_prefix: "[HYBRID:]"
              semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
              direct_prefix: "[DIRECT:]"
              on_semantic_rerank: fetch
              on_other: call_answer
              next: call_answer

            - id: fetch
              action: fetch_more_context
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: handle_answer

            - id: handle_answer
              action: handle_prefix
              answer_prefix: "[Answer:]"
              followup_prefix: "[FOLLOWUP:]"
              on_answer: persist
              on_other: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    yaml_path = _write_pipeline(tmp_path, yaml_text)
    pipe = _load_pipeline(tmp_path, yaml_path)

    model = FakeModelClient(
        outputs_by_consultant={
            "e2e/router_v1": ["[SEMANTIC_RERANK:] CS | checkout confirm create order"],
            "e2e/answer_v1": ["[Answer:] OK"],
        }
    )

    semantic = FakeRetriever(results=[])
    bm25 = FakeRetriever(results=[])
    rerank = FakeRetriever(results=[{"path": "a.cs", "content": "x"}])
    dispatcher = RetrievalDispatcher(semantic=semantic, bm25=bm25, semantic_rerank=rerank)

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
        history_manager=history_manager,
        logger=InteractionLogger(tmp_path / "ai_interaction.log"),
        token_counter=None,
        bm25_searcher=bm25,
        semantic_rerank_searcher=rerank,
        translator_pl_en=None,
    )

    state = PipelineState(
        user_query="E2E rerank",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    _ = _run_engine(pipe, state, rt)

    assert state.retrieval_mode == "semantic_rerank"
    assert state.retrieval_filters.get("data_type") == ["regular_code"]
    assert len(rerank.calls) == 1
    assert len(semantic.calls) == 0
    assert len(bm25.calls) == 0


def test_e2e_hybrid_routes_to_semantic_backend(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_hybrid
          settings:
            entry_step_id: call_router
            top_k: 1

          steps:
            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              bm25_prefix: "[BM25:]"
              semantic_prefix: "[SEMANTIC:]"
              hybrid_prefix: "[HYBRID:]"
              semantic_rerank_prefix: "[SEMANTIC_RERANK:]"
              direct_prefix: "[DIRECT:]"
              on_hybrid: fetch
              on_other: call_answer
              next: call_answer

            - id: fetch
              action: fetch_more_context
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: handle_answer

            - id: handle_answer
              action: handle_prefix
              answer_prefix: "[Answer:]"
              followup_prefix: "[FOLLOWUP:]"
              on_answer: persist
              on_other: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    yaml_path = _write_pipeline(tmp_path, yaml_text)
    pipe = _load_pipeline(tmp_path, yaml_path)

    model = FakeModelClient(
        outputs_by_consultant={
            "e2e/router_v1": ["[HYBRID:] ANY | find order persistence transaction"],
            "e2e/answer_v1": ["[Answer:] OK"],
        }
    )

    semantic = FakeRetriever(results=[{"path": "x.cs", "content": "y"}])
    bm25 = FakeRetriever(results=[{"path": "b.cs", "content": "c"}])
    rerank = FakeRetriever(results=[])
    dispatcher = RetrievalDispatcher(semantic=semantic, bm25=bm25, semantic_rerank=rerank)

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
        history_manager=history_manager,
        logger=InteractionLogger(tmp_path / "ai_interaction.log"),
        token_counter=None,
        bm25_searcher=bm25,
        semantic_rerank_searcher=rerank,
        translator_pl_en=None,
    )

    state = PipelineState(
        user_query="E2E hybrid",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    _ = _run_engine(pipe, state, rt)

    assert state.retrieval_mode == "hybrid"
    # HYBRID is currently treated as semantic in dispatcher
    assert len(semantic.calls) == 1
    assert len(bm25.calls) == 0


def test_e2e_context_budget_over_limit_routes_to_fallback_answer(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_budget
          settings:
            entry_step_id: translate
            top_k: 1
            max_history_tokens: 10

          steps:
            - id: translate
              action: translate_in_if_needed
              next: load_history

            - id: load_history
              action: load_conversation_history
              next: check_budget

            - id: check_budget
              action: check_context_budget
              input: history_for_prompt
              max_tokens_from_settings: max_history_tokens
              on_over_limit: call_fallback
              on_ok: call_router
              next: call_router

            - id: call_fallback
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: handle_answer

            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              direct_prefix: "[DIRECT:]"
              on_direct: call_answer
              on_other: call_answer
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: handle_answer

            - id: handle_answer
              action: handle_prefix
              answer_prefix: "[Answer:]"
              followup_prefix: "[FOLLOWUP:]"
              on_answer: persist
              on_other: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    yaml_path = _write_pipeline(tmp_path, yaml_text)
    pipe = _load_pipeline(tmp_path, yaml_path)

    model = FakeModelClient(
        outputs_by_consultant={
            # Fallback branch
            "e2e/answer_v1": ["[Answer:] BUDGET OVER LIMIT FALLBACK"],
            # Not expected to be used in this test if over_limit triggers early
            "e2e/router_v1": ["[DIRECT:]"],
        }
    )

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    # Prepopulate long history
    history_manager.start_user_query("PREV QUESTION " + ("x " * 5000), None)

    history_manager.add_iteration(
        codellama_query="MI " + ("y " * 5000),
        faiss_results=[{"path": "prev.txt", "content": ("z " * 5000)}],
    )
    history_manager.set_final_answer("PREV ANSWER " + ("z" * 8000))

    token_counter = FakeTokenCounter(fixed_count=9999)  # force over limit

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=None,
        history_manager=history_manager,
        logger=InteractionLogger(tmp_path / "ai_interaction.log"),
        token_counter=token_counter,
        translator_pl_en=DummyTranslator(),
    )

    state = PipelineState(
        user_query="Now",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=True,
    )

    out = _run_engine(pipe, state, rt)

    assert out.final_answer is not None
    assert "BUDGET OVER LIMIT FALLBACK" in (out.final_answer or "")
    assert "check_budget" in state.step_trace
    assert state.step_trace[-1] == "persist"
    assert len(token_counter.calls) >= 1


def test_e2e_loop_guard_denies_after_max_turn_loops(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_loop_guard
          settings:
            entry_step_id: call_router
            top_k: 1
            max_turn_loops: 1

          steps:
            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              direct_prefix: "[DIRECT:]"
              on_direct: call_answer
              on_other: call_answer
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: handle_answer

            - id: handle_answer
              action: handle_prefix
              answer_prefix: "[Answer:]"
              followup_prefix: "[FOLLOWUP:]"
              on_answer: persist
              on_followup: loop_guard
              on_other: persist

            - id: loop_guard
              action: loop_guard
              max_turn_loops_from_settings: max_turn_loops
              on_allow: fetch
              on_deny: call_final
              next: fetch

            - id: fetch
              action: fetch_more_context
              next: call_answer

            - id: call_final
              action: call_model
              prompt_key: "e2e/final_v1"
              next: handle_final

            - id: handle_final
              action: handle_prefix
              answer_prefix: "[Answer:]"
              followup_prefix: "[FOLLOWUP:]"
              on_answer: persist
              on_other: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    yaml_path = _write_pipeline(tmp_path, yaml_text)
    pipe = _load_pipeline(tmp_path, yaml_path)

    # First answer model emits FOLLOWUP twice -> second time should be denied by loop_guard(max=1)
    model = FakeModelClient(
        outputs_by_consultant={
            "e2e/router_v1": ["[DIRECT:]"],
            "e2e/answer_v1": [
                "[FOLLOWUP:] need more context A",
                "[FOLLOWUP:] need more context B",
            ],
            "e2e/final_v1": ["[Answer:] STOPPED BY LOOP GUARD"],
        }
    )

    retr = FakeRetriever(results=[{"path": "x.cs", "content": "y"}])
    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr, semantic_rerank=retr)

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
        history_manager=history_manager,
        logger=InteractionLogger(tmp_path / "ai_interaction.log"),
        token_counter=None,
        bm25_searcher=retr,
        semantic_rerank_searcher=retr,
        translator_pl_en=None,
    )

    state = PipelineState(
        user_query="Loop test",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = _run_engine(pipe, state, rt)

    assert out.final_answer is not None
    assert "STOPPED BY LOOP GUARD" in (out.final_answer or "")

    # Ensure we actually tried fetching once (first followup allowed)
    assert len(retr.calls) == 1

    # Ensure loop_guard was executed
    assert "loop_guard" in state.step_trace
    assert state.step_trace[-1] == "persist"


def test_e2e_graph_actions_are_noop_but_do_not_break_flow(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        """
        YAMLpipeline:
          name: e2e_graph_noop
          settings:
            entry_step_id: call_router
            top_k: 1

          steps:
            - id: call_router
              action: call_model
              prompt_key: "e2e/router_v1"
              next: handle_router

            - id: handle_router
              action: handle_prefix
              bm25_prefix: "[BM25:]"
              on_bm25: fetch
              on_other: fetch
              next: fetch

            - id: fetch
              action: fetch_more_context
              next: expand

            - id: expand
              action: expand_dependency_tree
              next: fetch_nodes

            - id: fetch_nodes
              action: fetch_node_texts
              next: call_answer

            - id: call_answer
              action: call_model
              prompt_key: "e2e/answer_v1"
              next: handle_answer

            - id: handle_answer
              action: handle_prefix
              answer_prefix: "[Answer:]"
              on_answer: persist
              on_other: persist

            - id: persist
              action: persist_turn_and_finalize
              end: true
        """
    )

    yaml_path = _write_pipeline(tmp_path, yaml_text)
    pipe = _load_pipeline(tmp_path, yaml_path)

    model = FakeModelClient(
        outputs_by_consultant={
            "e2e/router_v1": ["[BM25:] ANY | something"],
            "e2e/answer_v1": ["[Answer:] OK"],
        }
    )

    retr = FakeRetriever(results=[{"path": "x.cs", "content": "y"}])
    dispatcher = RetrievalDispatcher(semantic=retr, bm25=retr, semantic_rerank=retr)

    redis = InMemoryMockRedis()
    history_manager = HistoryManager(backend=redis, session_id="s")

    rt = _runtime(
        pipeline_settings=pipe.settings,
        model=model,
        dispatcher=dispatcher,
        history_manager=history_manager,
        logger=InteractionLogger(tmp_path / "ai_interaction.log"),
        token_counter=None,
        bm25_searcher=retr,
        semantic_rerank_searcher=retr,
        translator_pl_en=None,
    )

    state = PipelineState(
        user_query="Graph noop",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = _run_engine(pipe, state, rt)

    assert out.final_answer is not None
    assert "OK" in (out.final_answer or "")
    assert "expand" in state.step_trace
    assert "fetch_nodes" in state.step_trace
