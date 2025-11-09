# File: code_query_engine/log_utils.py
from __future__ import annotations

import logging
from logging import Logger
from pathlib import Path
from datetime import datetime
from typing import List, Optional
import json
import os


class InteractionLogger:
    """
    Logger for recording the lifecycle of interactions with the model.

    Responsibilities:
    - Read the log file path from `config.json` (key: `"log_path"`).
    - Ensure target directories exist and configure the logger once.
    - Provide a simple, single-entry API: `log_interaction(...)`.

    Notes:
    - If the environment variable `AI_LOG_STDOUT` is set to `1/true/yes`,
      logs are duplicated to stdout (useful during local development or CI).
    """

    _instance: Optional["InteractionLogger"] = None

    def __init__(self, log_file: Path, logger_name: str = "ai_logger") -> None:
        self.log_file = log_file
        self.logger: Logger = logging.getLogger(logger_name)
        if not self.logger.handlers:
            self._configure_logger()

    # ---------- Factories ----------

    @classmethod
    def from_project_root(cls, config_filename: str = "config.json") -> "InteractionLogger":
        """
        Create an instance using `config.json` located at the project root.

        The project root is assumed to be two levels up from this file:
        `<repo_root>/<this_package>/.../log_utils.py`
        """
        project_root = Path(__file__).resolve().parent.parent
        cfg_path = project_root / config_filename

        with cfg_path.open(encoding="utf-8") as f:
            cfg = json.load(f)

        log_path = project_root / cfg["log_path"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(log_path)

    @classmethod
    def instance(cls) -> "InteractionLogger":
        """
        Simple singleton accessor — convenient for web apps or background workers.
        """
        if cls._instance is None:
            cls._instance = cls.from_project_root()
        return cls._instance

    # ---------- Private ----------

    def _configure_logger(self) -> None:
        """
        Configure the underlying logger (file handler and optional stdout handler).
        """
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler(self.log_file, encoding="utf-8")
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        # Optional stdout duplication (for dev/CI visibility)
        if os.getenv("AI_LOG_STDOUT", "0").lower() in ("1", "true", "yes"):
            sh = logging.StreamHandler()
            sh.setFormatter(formatter)
            self.logger.addHandler(sh)

    # ---------- Public API ----------

    def log_interaction(
        self,
        *,
        original_question: str,
        model_input_en: str,
        codellama_response: Optional[str],
        followup_query: Optional[str],
        query_type: str,
        final_answer: Optional[str],
        context_blocks: List[str],
        next_codellama_prompt: Optional[str] = None,
    ) -> None:
        """
        Write a single, human-readable log entry summarizing the interaction.

        Parameters
        ----------
        original_question : str
            The original user question.
        model_input_en : str
            The English prompt sent to the model after any preprocessing/translation.
        codellama_response : Optional[str]
            Raw response produced by CodeLlama at this stage (may be empty).
        followup_query : Optional[str]
            A follow-up query decided by the controller (if any).
        query_type : str
            Type/category of the current query (e.g., ANSWER / FOLLOWUP).
        final_answer : Optional[str]
            Final answer returned to the user (if already decided).
        context_blocks : List[str]
            Context snippets that were provided to the model.
        next_codellama_prompt : Optional[str]
            Next prompt that will be sent to CodeLlama (if applicable).
        """
        sep = "=" * 40
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Normalize missing values to keep the log consistent
        final_answer = final_answer.strip() if final_answer and final_answer.strip() else "<empty>"
        codellama_response = (
            codellama_response.strip() if codellama_response and codellama_response.strip() else "<empty>"
        )

        lines: List[str] = [
            f"{sep}\n{ts} - START : Original question",
            f"{(original_question or '').strip()}",
            f"{sep}",
            f'Translated (EN) : "{(model_input_en or "").strip()}"',
            f'\nCodeLlama replied : "{codellama_response}"',
            (f'\nFollow-up decided : "{followup_query.strip()}"' if followup_query else ""),
            f"\nQuery type       : {query_type}",
            f"\nFinal answer     :\n{final_answer}\n",
            "Context used:\n",
        ]

        for i, block in enumerate(context_blocks or []):
            pretty = (block or "").strip().replace("\n", "\n    ")
            lines.append(f"[Context {i+1}]\n    {pretty}\n")

        if next_codellama_prompt:
            lines.append(f"Next CodeLlama prompt:\n{next_codellama_prompt.strip()}\n")

        lines.append("\n")
        self.logger.info("\n".join([ln for ln in lines if ln]))
