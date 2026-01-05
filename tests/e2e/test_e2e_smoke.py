from __future__ import annotations

from pathlib import Path

import pytest

from code_query_engine.dynamic_pipeline import DynamicPipelineRunner
from code_query_engine.log_utils import InteractionLogger
from code_query_engine.pipeline.providers.fakes import FakeModelClient, FakeRetriever
from history.mock_redis import InMemoryMockRedis


def _run_pipeline(*, pipelines_root: Path, model: FakeModelClient, retriever: FakeRetriever, log_file: Path):
    runner = DynamicPipelineRunner(
        pipelines_root=str(pipelines_root),
        main_model=model,
        searcher=retriever,  # kept for backward-compat; retrieval dispatcher uses it only in some actions
        markdown_translator=None,
        translator_pl_en=None,
        logger=InteractionLogger(log_file),
        bm25_searcher=retriever,
        semantic_rerank_searcher=retriever,
        graph_provider=None,
        token_counter=None,
        allow_test_pipelines=True,
    )

    mock_redis = InMemoryMockRedis()

    final_answer, query_type, steps_used, model_input_en = runner.run(
        user_query="E2E: smoke",
        session_id="test-session",
        consultant="e2e_smoke",
        branch="develop",
        translate_chat=False,
        mock_redis=mock_redis,
    )

    return final_answer, query_type, steps_used, model_input_en


def test_e2e_smoke_direct_answer(tmp_path: Path) -> None:
    pipelines_root = Path(__file__).resolve().parent / "data" / "pipelines"
    log_file = tmp_path / "ai_interaction.log"

    model = FakeModelClient(
    outputs_by_consultant={
        "e2e_smoke": [
            "[DIRECT:]",
            "[Answer:] E2E OK",
        ],
    }
)


    retriever = FakeRetriever(results=[])

    final_answer, query_type, steps_used, model_input_en = _run_pipeline(
        pipelines_root=pipelines_root,
        model=model,
        retriever=retriever,
        log_file=log_file,
    )

    assert "E2E OK" in final_answer
    assert query_type in ("DIRECT", "ANSWER", None)
    assert steps_used >= 1
    assert model_input_en == "E2E: smoke"

    content = log_file.read_text(encoding="utf-8", errors="replace")
    assert "User question:" in content
    assert "Answer:" in content


def test_e2e_test_pipeline_is_blocked_without_opt_in(tmp_path: Path) -> None:
    pipelines_root = Path(__file__).resolve().parent / "data" / "pipelines"
    log_file = tmp_path / "ai_interaction.log"

    runner = DynamicPipelineRunner(
        pipelines_root=str(pipelines_root),
        main_model=FakeModelClient(outputs=["[DIRECT:]"]),
        searcher=FakeRetriever(results=[]),
        markdown_translator=None,
        translator_pl_en=None,
        logger=InteractionLogger(log_file),
        allow_test_pipelines=False,
    )

    with pytest.raises(PermissionError):
        runner.run(
            user_query="E2E: should fail",
            session_id="test-session",
            consultant="e2e_smoke",
            branch="develop",
            translate_chat=False,
            mock_redis=InMemoryMockRedis(),
        )
