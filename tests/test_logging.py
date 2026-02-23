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


def test_interaction_logger_writes_minimal_sections(tmp_path: Path) -> None:
    log_file = tmp_path / "ai_interaction.log"
    logger = InteractionLogger(log_file)

    logger.log_interaction(
        session_id="s1",
        pipeline_name="p1",
        step_id="finalize",
        action="persist_turn",
        data={
            "user_question": "Q_PL: ile to kosztuje?",
            "translate_chat": True,
            "translated_question_en": "Q_EN: how much does it cost?",
            "consultant": "rejewski",
            "branch_a": "2025-12-14__release_4_90",
            "branch_b": "2025-12-14__release_4_60",
            "answer": "A_PL: kosztuje 10.",
        },
    )

    _flush_handlers(logger)

    content = log_file.read_text(encoding="utf-8", errors="replace")

    assert "User question:" in content
    assert "Q_PL: ile to kosztuje?" in content

    assert "Is Polish:" in content
    assert "true" in content  # serialized boolean

    assert "Translated (EN):" in content
    assert "Q_EN: how much does it cost?" in content

    assert "Consultant:" in content
    assert "rejewski" in content

    assert "BranchA:" in content
    assert "2025-12-14__release_4_90" in content

    assert "BranchB:" in content
    assert "2025-12-14__release_4_60" in content

    assert "Answer:" in content
    assert "A_PL: kosztuje 10." in content

    # Legacy sections must NOT be emitted by the minimal logger.
    assert "CodeLlama replied" not in content
    assert "Context blocks" not in content
    assert "[Context 1]" not in content


def test_interaction_logger_does_not_duplicate_handlers(tmp_path: Path) -> None:
    log_file = tmp_path / "ai_interaction.log"
    logger = InteractionLogger(log_file)

    handlers_before = len(logger.logger.handlers)

    logger.log_interaction(
        data={
            "user_question": "Q1",
            "translate_chat": False,
            "translated_question_en": "Q1",
            "consultant": "rejewski",
            "branch_a": "b1",
            "branch_b": None,
            "answer": "A1",
        }
    )
    logger.log_interaction(
        data={
            "user_question": "Q2",
            "translate_chat": False,
            "translated_question_en": "Q2",
            "consultant": "rejewski",
            "branch_a": "b1",
            "branch_b": None,
            "answer": "A2",
        }
    )

    handlers_after = len(logger.logger.handlers)
    assert handlers_after == handlers_before
