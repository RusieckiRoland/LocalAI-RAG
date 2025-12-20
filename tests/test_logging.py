# tests/test_logging.py
from __future__ import annotations

from pathlib import Path

from code_query_engine.log_utils import InteractionLogger


def _flush_handlers(logger: InteractionLogger) -> None:
    for h in list(logger.logger.handlers):
        try:
            h.flush()
        except Exception:
            pass


def test_interaction_logger_writes_expected_sections(tmp_path: Path) -> None:
    log_file = tmp_path / "ai_interaction.log"
    logger = InteractionLogger(log_file)

    logger.log_interaction(
        original_question="Q_PL: ile to kosztuje?",
        model_input_en="Q_EN: how much does it cost?",
        codellama_response="ANSWER: It costs 10.",
        followup_query=None,
        query_type="ANSWER",
        final_answer="It costs 10.",
        context_blocks=[
            "File: a.py\nprint('hello')",
            "File: b.py\nprint('world')",
        ],
        next_codellama_prompt="prompts/rejewski/answerer_v1.txt",
    )

    _flush_handlers(logger)

    content = log_file.read_text(encoding="utf-8", errors="replace")

    assert "Translated (EN)" in content
    assert "CodeLlama replied" in content
    assert "Query type:" in content
    assert "Final answer" in content

    assert "[Context 1]" in content
    assert "[Context 2]" in content

    assert "File: a.py" in content
    assert "print('hello')" in content


def test_interaction_logger_does_not_duplicate_handlers(tmp_path: Path) -> None:
    log_file = tmp_path / "ai_interaction.log"
    logger = InteractionLogger(log_file)

    handlers_before = len(logger.logger.handlers)

    logger.log_interaction(
        original_question="Q1",
        model_input_en="Q1_EN",
        codellama_response="R1",
        followup_query="FU1",
        query_type="FOLLOWUP",
        final_answer=None,
        context_blocks=["ctx1"],
        next_codellama_prompt=None,
    )
    logger.log_interaction(
        original_question="Q2",
        model_input_en="Q2_EN",
        codellama_response="R2",
        followup_query=None,
        query_type="ANSWER",
        final_answer="A2",
        context_blocks=["ctx2"],
        next_codellama_prompt=None,
    )

    handlers_after = len(logger.logger.handlers)
    assert handlers_after == handlers_before
