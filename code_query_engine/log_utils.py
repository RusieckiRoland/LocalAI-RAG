# code_query_engine/log_utils.py
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import List, Optional


class InteractionLogger:
    """
    Minimal, deterministic interaction logger.
    Writes human-readable text blocks (easy to grep in tests and in production).

    Notes:
    - If AI_LOG_STDOUT=1/true/yes, duplicates logs to stdout (useful in CI).
    """

    def __init__(self, log_file: Path, logger_name: str = "ai_interaction") -> None:
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger: Logger = logging.getLogger(logger_name)
        # IMPORTANT: configure exactly once (avoid duplicate handlers)
        if not self.logger.handlers:
            self._configure_logger()

    def _configure_logger(self) -> None:
        self.logger.setLevel(logging.INFO)

        fmt = logging.Formatter("%(message)s")

        fh = logging.FileHandler(self.log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)

        if os.getenv("AI_LOG_STDOUT", "0").lower() in ("1", "true", "yes"):
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            self.logger.addHandler(sh)

    def log_interaction(
        self,
        *,
        original_question: str,
        model_input_en: str,
        codellama_response: Optional[str],
        followup_query: Optional[str],
        query_type: Optional[str],
        final_answer: Optional[str],
        context_blocks: List[str],
        next_codellama_prompt: Optional[str] = None,
    ) -> None:
        ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        lines: List[str] = []
        lines.append("=" * 80)
        lines.append(f"Timestamp: {ts}")
        if next_codellama_prompt:
            lines.append(f"Prompt: {next_codellama_prompt}")

        lines.append("")
        lines.append("Original question")
        lines.append(original_question or "")

        lines.append("")
        lines.append("Translated (EN)")
        lines.append(model_input_en or "")

        lines.append("")
        lines.append("CodeLlama replied")
        lines.append(codellama_response or "")

        lines.append("")
        lines.append(f"Query type: {query_type or ''}")
        if followup_query:
            lines.append(f"Followup query: {followup_query}")

        lines.append("")
        lines.append("Final answer")
        lines.append(final_answer or "")

        if context_blocks:
            lines.append("")
            lines.append("Context blocks")
            for i, block in enumerate(context_blocks, start=1):
                lines.append(f"[Context {i}]")
                lines.append(block or "")

        # Also add a compact JSON line to make future parsing easy
        payload = {
            "ts": ts,
            "prompt": next_codellama_prompt,
            "original_question": original_question,
            "model_input_en": model_input_en,
            "codellama_response": codellama_response,
            "followup_query": followup_query,
            "query_type": query_type,
            "final_answer": final_answer,
            "context_blocks_count": len(context_blocks or []),
        }
        lines.append("")
        lines.append("JSON")
        lines.append(json.dumps(payload, ensure_ascii=False))

        self.logger.info("\n".join(lines))
