# common/logging_setup.py
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
from dataclasses import dataclass
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


TRACE_LEVEL_NUM = 5


def _add_trace_level() -> None:
    """
    Add TRACE level to Python logging (below DEBUG).
    This is a common server-side pattern when you need ultra-verbose logs.
    """
    if hasattr(logging, "TRACE"):
        return

    logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")
    setattr(logging, "TRACE", TRACE_LEVEL_NUM)

    def trace(self: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(TRACE_LEVEL_NUM):
            self._log(TRACE_LEVEL_NUM, msg, args, **kwargs)

    setattr(logging.Logger, "trace", trace)


class _JsonFormatter(logging.Formatter):
    """
    Minimal JSON formatter for structured logs.

    Note:
    - We keep it simple and deterministic.
    - Message stays in "message".
    - Extra fields can be passed via "extra={...}".
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Common extras (if present)
        for k in (
            "event",
            "session_id",
            "consultant",
            "branch",
            "turn",
        ):
            if hasattr(record, k):
                payload[k] = getattr(record, k)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def _gzip_rotator(source: str, dest: str) -> None:
    """
    Compress rotated log into gzip.
    """
    with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    try:
        os.remove(source)
    except Exception:
        pass


def _gzip_namer(name: str) -> str:
    return f"{name}.gz"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _parse_level(level: str, default: int) -> int:
    v = (level or "").strip().upper()
    if not v:
        return default
    return getattr(logging, v, default)


def _project_root_from_here() -> Path:
    # <repo_root>/common/logging_setup.py
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class LoggingConfig:
    log_dir: Path
    app_log_name: str = "app.log"
    interactions_log_name: str = "ai_interactions.jsonl"

    # Rotation
    when: str = "midnight"  # daily
    interval: int = 1
    backup_count: int = 14  # keep 14 days
    utc: bool = False

    # Levels
    app_level: int = logging.INFO
    interactions_level: int = TRACE_LEVEL_NUM

    # Optional console duplication
    also_stdout: bool = False


def load_logging_config_from_cfg(cfg: Dict[str, Any], project_root: Optional[Path] = None) -> LoggingConfig:
    """
    Supports:
    - new: cfg["logging"] object
    - legacy: cfg["log_path"] (we will derive directory from it)
    """
    project_root = project_root or _project_root_from_here()

    logging_cfg = cfg.get("logging") or {}
    if not isinstance(logging_cfg, dict):
        logging_cfg = {}

    # Legacy support: "log_path": "log/ai_interaction.log"
    legacy_log_path = cfg.get("log_path")
    if isinstance(legacy_log_path, str) and legacy_log_path.strip():
        legacy_dir = (project_root / legacy_log_path).parent
    else:
        legacy_dir = project_root / "log"

    log_dir = project_root / (logging_cfg.get("dir") or legacy_dir)
    _ensure_dir(log_dir)

    app_level = _parse_level(str(logging_cfg.get("level") or ""), logging.INFO)
    interactions_level = _parse_level(str(logging_cfg.get("interactions_level") or "TRACE"), TRACE_LEVEL_NUM)

    also_stdout = str(os.getenv("AI_LOG_STDOUT") or "").strip().lower() in ("1", "true", "yes")
    if "also_stdout" in logging_cfg:
        also_stdout = bool(logging_cfg.get("also_stdout"))

    return LoggingConfig(
        log_dir=log_dir,
        app_log_name=str(logging_cfg.get("app_file") or "app.log"),
        interactions_log_name=str(logging_cfg.get("interactions_file") or "ai_interactions.jsonl"),
        when=str(logging_cfg.get("when") or "midnight"),
        interval=int(logging_cfg.get("interval") or 1),
        backup_count=int(logging_cfg.get("backup_count") or 14),
        utc=bool(logging_cfg.get("utc") or False),
        app_level=app_level,
        interactions_level=interactions_level,
        also_stdout=also_stdout,
    )


def configure_logging(cfg: Dict[str, Any], *, project_root: Optional[Path] = None) -> LoggingConfig:
    """
    Configure:
    - root logger -> app.log (human readable)
    - localai.interactions -> ai_interactions.jsonl (JSONL)
    """
    _add_trace_level()

    config = load_logging_config_from_cfg(cfg, project_root=project_root)

    # --- Root logger (application logs) ---
    root = logging.getLogger()
    root.setLevel(min(config.app_level, config.interactions_level, logging.DEBUG))

    # Avoid double-handlers if configure_logging() called multiple times (tests, reload, etc.)
    if getattr(root, "_localai_configured", False):
        return config

    # Human readable formatter for app.log
    app_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    app_path = config.log_dir / config.app_log_name
    app_handler = TimedRotatingFileHandler(
        filename=str(app_path),
        when=config.when,
        interval=config.interval,
        backupCount=config.backup_count,
        utc=config.utc,
        encoding="utf-8",
        delay=True,
    )
    app_handler.setLevel(config.app_level)
    app_handler.setFormatter(app_fmt)
    app_handler.rotator = _gzip_rotator
    app_handler.namer = _gzip_namer

    root.addHandler(app_handler)

    if config.also_stdout:
        console = logging.StreamHandler()
        console.setLevel(config.app_level)
        console.setFormatter(app_fmt)
        root.addHandler(console)

    # --- Interactions logger (JSONL) ---
    interactions_logger = logging.getLogger("localai.interactions")
    interactions_logger.setLevel(config.interactions_level)
    interactions_logger.propagate = False  # do not duplicate into app.log by default

    interactions_path = config.log_dir / config.interactions_log_name
    interactions_handler = TimedRotatingFileHandler(
        filename=str(interactions_path),
        when=config.when,
        interval=config.interval,
        backupCount=config.backup_count,
        utc=config.utc,
        encoding="utf-8",
        delay=True,
    )
    interactions_handler.setLevel(config.interactions_level)
    interactions_handler.setFormatter(_JsonFormatter())
    interactions_handler.rotator = _gzip_rotator
    interactions_handler.namer = _gzip_namer

    interactions_logger.addHandler(interactions_handler)

    setattr(root, "_localai_configured", True)
    return config


class InteractionLogger:
    """
    Drop-in implementation compatible with your pipeline's IInteractionLogger port.
    Writes a single JSON line per call into log/ai_interactions.jsonl (rotated + gzipped).
    """

    def __init__(self) -> None:
        _add_trace_level()
        self._logger = logging.getLogger("localai.interactions")

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
    ) -> None:
        payload: Dict[str, Any] = {
            "original_question": original_question,
            "model_input_en": model_input_en,
            "codellama_response": codellama_response,
            "followup_query": followup_query,
            "query_type": query_type,
            "final_answer": final_answer,
            "context_blocks": list(context_blocks),
            "next_codellama_prompt": next_codellama_prompt,
        }

        # We store payload as JSON inside the "message" field of JSONL formatter.
        # This keeps the formatter deterministic and avoids leaking huge extras into LogRecord.
        self._logger.log(TRACE_LEVEL_NUM, json.dumps(payload, ensure_ascii=False), extra={"event": "interaction"})
