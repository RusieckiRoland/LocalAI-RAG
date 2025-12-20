# code_query_engine/log_utils.py
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union


_PathLike = Union[str, Path]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class InteractionLogger:
    """
    Backward-compatible interaction logger used by tests.

    - Tests expect: InteractionLogger(log_file_path)
    - Writes a human-readable trace into that file.
    - Also appends a compact JSON record at the end of each interaction block.
    - Avoids handler duplication across multiple instances.
    """

    def __init__(self, log_file: _PathLike, logger_name: str = "ai_interaction") -> None:
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        # Do not duplicate handlers (tests assert this behavior)
        abs_path = str(self.log_file.resolve())
        for h in list(self.logger.handlers):
            if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == abs_path:
                return

        fh = logging.FileHandler(abs_path, encoding="utf-8")
        fh.setLevel(logging.INFO)

        # Keep it clean: only the message text (no timestamps/levels duplicated)
        fh.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(fh)

    def log_interaction(
        self,
        *,
        original_question: str,
        model_input_en: str,
        codellama_response: str,
        followup_query: Optional[str],
        query_type: Optional[str],
        final_answer: Optional[str],
        context_blocks: Sequence[str],
        next_codellama_prompt: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ts = _utc_now_iso()

        # Human readable block
        self.logger.info("=" * 116)
        self.logger.info(f"Timestamp: {ts}")
        if next_codellama_prompt:
            self.logger.info(f"Prompt: {next_codellama_prompt}")
        self.logger.info("")

        self.logger.info("Original question:")
        self.logger.info(original_question or "")
        self.logger.info("")

        self.logger.info("Translated (EN):")
        self.logger.info(model_input_en or "")
        self.logger.info("")

        self.logger.info("CodeLlama replied:")
        self.logger.info(codellama_response or "")
        self.logger.info("")

        self.logger.info(f"Query type: {query_type or ''}")
        if followup_query:
            self.logger.info(f"Follow-up query: {followup_query}")
        self.logger.info("")

        self.logger.info("Final answer:")
        self.logger.info(final_answer or "")
        self.logger.info("")

        self.logger.info("Context blocks:")
        if context_blocks:
            for i, blk in enumerate(context_blocks, start=1):
                self.logger.info(f"[Context {i}]")
                self.logger.info(blk or "")
                self.logger.info("")
        else:
            self.logger.info("(none)")
            self.logger.info("")

        # JSON record at the end (append-only, one per interaction)
        rec: Dict[str, Any] = {
            "timestamp": ts,
            "original_question": original_question,
            "model_input_en": model_input_en,
            "codellama_response": codellama_response,
            "followup_query": followup_query,
            "query_type": query_type,
            "final_answer": final_answer,
            "context_blocks": list(context_blocks),
            "next_codellama_prompt": next_codellama_prompt,
        }
        if metadata:
            rec["metadata"] = metadata

        self.logger.info("JSON:")
        self.logger.info(json.dumps(rec, ensure_ascii=False))
        self.logger.info("")  # trailing newline separator
