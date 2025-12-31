from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------
# Logging config
# ------------------------------------------------------------

@dataclass(frozen=True)
class LoggingConfig:
    log_dir: Path = Path("log")
    level: str = "INFO"
    when: str = "midnight"
    interval: int = 1
    backup_count: int = 14
    also_stdout: bool = False

    app_file: str = "app.log"

    # Interaction logs
    interactions_level: str = "TRACE"
    interactions_file: str = "ai_interactions.jsonl"

    # Human-readable interaction log
    human_log: bool = True
    human_file: str = "ai_interaction.log"

    # JSONL capture
    capture_jsonl: bool = True

    # Optional: emit a pointer line to app.log when interaction was written
    emit_app_log_pointers: bool = False


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


_TRACE_LEVEL = 5
if not hasattr(logging, "TRACE"):
    logging.addLevelName(_TRACE_LEVEL, "TRACE")

    def _trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(_TRACE_LEVEL):
            self._log(_TRACE_LEVEL, message, args, **kwargs)

    logging.Logger.trace = _trace  # type: ignore[attr-defined]


def configure_logging(cfg: LoggingConfig) -> None:
    _ensure_dir(cfg.log_dir)

    root = logging.getLogger()
    root.setLevel(getattr(logging, str(cfg.level).upper(), logging.INFO))

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Avoid duplicate handlers across multiple imports / tests
    if not any(getattr(h, "_localai_app", False) for h in root.handlers):
        app_path = cfg.log_dir / cfg.app_file
        fh = TimedRotatingFileHandler(
            filename=str(app_path),
            when=cfg.when,
            interval=cfg.interval,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh._localai_app = True  # type: ignore[attr-defined]
        root.addHandler(fh)

    if cfg.also_stdout and not any(isinstance(h, logging.StreamHandler) and getattr(h, "_localai_stdout", False) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh._localai_stdout = True  # type: ignore[attr-defined]
        root.addHandler(sh)

    # JSONL interaction logger (shared)
    if cfg.capture_jsonl:
        interactions_logger = logging.getLogger("localai.interactions")
        interactions_logger.setLevel(_TRACE_LEVEL)
        interactions_logger.propagate = False

        interactions_path = (cfg.log_dir / cfg.interactions_file).resolve()
        if not any(getattr(h, "_localai_interactions_path", None) == str(interactions_path) for h in interactions_logger.handlers):
            ih = TimedRotatingFileHandler(
                filename=str(interactions_path),
                when=cfg.when,
                interval=cfg.interval,
                backupCount=cfg.backup_count,
                encoding="utf-8",
            )
            ih.setFormatter(logging.Formatter("%(message)s"))
            ih._localai_interactions_path = str(interactions_path)  # type: ignore[attr-defined]
            interactions_logger.addHandler(ih)

    # Human interaction log (shared)
    if cfg.human_log:
        human_logger = logging.getLogger("localai.interactions.human")
        human_logger.setLevel(logging.INFO)
        human_logger.propagate = False

        human_path = (cfg.log_dir / cfg.human_file).resolve()
        if not any(getattr(h, "_localai_human_path", None) == str(human_path) for h in human_logger.handlers):
            hh = TimedRotatingFileHandler(
                filename=str(human_path),
                when=cfg.when,
                interval=cfg.interval,
                backupCount=cfg.backup_count,
                encoding="utf-8",
            )
            hh.setFormatter(logging.Formatter("%(message)s"))
            hh._localai_human_path = str(human_path)  # type: ignore[attr-defined]
            human_logger.addHandler(hh)


def logging_config_from_runtime_config(runtime_cfg: Dict[str, Any]) -> LoggingConfig:
    logging_cfg = runtime_cfg.get("logging") or {}
    ai_cfg = logging_cfg.get("ai_interaction") or {}

    log_dir = Path(str(logging_cfg.get("dir") or "log"))

    return LoggingConfig(
        log_dir=log_dir,
        level=str(logging_cfg.get("level") or "INFO"),
        when=str(logging_cfg.get("when") or "midnight"),
        interval=int(logging_cfg.get("interval") or 1),
        backup_count=int(logging_cfg.get("backup_count") or 14),
        also_stdout=bool(logging_cfg.get("also_stdout") or False),
        app_file=str(logging_cfg.get("app_file") or "app.log"),
        interactions_level=str(logging_cfg.get("interactions_level") or "TRACE"),
        interactions_file=str(logging_cfg.get("interactions_file") or "ai_interactions.jsonl"),
        capture_jsonl=bool(ai_cfg.get("capture_jsonl") if "capture_jsonl" in ai_cfg else logging_cfg.get("ai_interactions_jsonl", True)),
        human_log=bool(ai_cfg.get("human_log") if "human_log" in ai_cfg else logging_cfg.get("ai_interactions_human", True)),
        human_file=str(ai_cfg.get("human_file") or logging_cfg.get("human_file") or "ai_interaction.log"),
        emit_app_log_pointers=bool(ai_cfg.get("emit_app_log_pointers") or False),
    )


# ------------------------------------------------------------
# Interaction logger
# ------------------------------------------------------------

class InteractionLogger:
    """
    Minimal AI interaction logger (human + JSONL).

    Version A: one stable human format (no duplicate labels).
    Tests should validate these exact labels:
      - User question:
      - Is Polish:
      - Translated (EN):
      - Consultant:
      - BranchA:
      - BranchB:
      - Answer:
      - JSON:
    """

    def __init__(self, log_file: Optional[Path | str] = None, *, cfg: Optional[LoggingConfig] = None) -> None:
        base_cfg = cfg or LoggingConfig()

        # Legacy compat: InteractionLogger("/path/to/ai_interaction.log")
        if log_file is not None:
            p = Path(str(log_file))
            base_cfg = LoggingConfig(
                log_dir=p.parent,
                app_file=base_cfg.app_file,
                level=base_cfg.level,
                when=base_cfg.when,
                interval=base_cfg.interval,
                backup_count=base_cfg.backup_count,
                also_stdout=base_cfg.also_stdout,
                interactions_level=base_cfg.interactions_level,
                interactions_file=base_cfg.interactions_file,
                human_log=True,
                human_file=p.name,
                capture_jsonl=base_cfg.capture_jsonl,
                emit_app_log_pointers=base_cfg.emit_app_log_pointers,
            )

        self._cfg = base_cfg
        _ensure_dir(self._cfg.log_dir)

        self._capture_enabled = bool(self._cfg.capture_jsonl)
        self._human_enabled = bool(self._cfg.human_log)

        self._jsonl_path = (self._cfg.log_dir / self._cfg.interactions_file).resolve()
        self._human_path = (self._cfg.log_dir / self._cfg.human_file).resolve()

        # In tests (log_file passed), isolate by instance logger name to avoid handler leaks.
        self._instance_id = uuid.uuid4().hex

        if log_file is not None:
            self._jsonl_logger = logging.getLogger(f"localai.interactions.{self._instance_id}")
            self._human_logger = logging.getLogger(f"localai.interactions.human.{self._instance_id}")
        else:
            self._jsonl_logger = logging.getLogger("localai.interactions")
            self._human_logger = logging.getLogger("localai.interactions.human")

        self._jsonl_logger.setLevel(_TRACE_LEVEL)
        self._jsonl_logger.propagate = False

        self._human_logger.setLevel(logging.INFO)
        self._human_logger.propagate = False

        # Attach handlers eagerly in tests so handler-count test is stable.
        if log_file is not None:
            if self._capture_enabled:
                ih = TimedRotatingFileHandler(
                    filename=str(self._jsonl_path),
                    when=self._cfg.when,
                    interval=self._cfg.interval,
                    backupCount=self._cfg.backup_count,
                    encoding="utf-8",
                )
                ih.setFormatter(logging.Formatter("%(message)s"))
                self._jsonl_logger.addHandler(ih)

            if self._human_enabled:
                hh = TimedRotatingFileHandler(
                    filename=str(self._human_path),
                    when=self._cfg.when,
                    interval=self._cfg.interval,
                    backupCount=self._cfg.backup_count,
                    encoding="utf-8",
                )
                hh.setFormatter(logging.Formatter("%(message)s"))
                self._human_logger.addHandler(hh)

        # Legacy tests use logger.logger.handlers
        self.logger = self._human_logger

    def log_interaction(
        self,
        *,
        session_id: str = "",
        pipeline_name: str = "",
        step_id: str = "",
        action: str = "",
        data: Optional[Dict[str, Any]] = None,
        # Legacy kwargs kept for compatibility (but not emitted as separate fields)
        original_question: str = "",
        model_input_en: str = "",
        codellama_response: str = "",
        followup_query: Optional[str] = None,
        query_type: Optional[str] = None,
        final_answer: Optional[str] = None,
        context_blocks: Optional[List[str]] = None,
        next_codellama_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if data is None:
            data = {
                "user_question": original_question,
                "translate_chat": None,
                "translated_question_en": model_input_en,
                "consultant": "",
                "branch_a": "",
                "branch_b": None,
                "answer": final_answer or codellama_response,
            }
            if isinstance(metadata, dict):
                for k in ("consultant", "branch_a", "branch_b", "translate_chat"):
                    if k in metadata and data.get(k) in (None, ""):
                        data[k] = metadata.get(k)

        user_question = str(data.get("user_question") or data.get("original_question") or "")
        translated_question_en = str(data.get("translated_question_en") or data.get("model_input_en") or "")

        translate_chat_val = data.get("translate_chat")
        if translate_chat_val is None:
            translate_chat_val = data.get("translateChat")
        is_polish = bool(translate_chat_val) if translate_chat_val is not None else False

        consultant = str(data.get("consultant") or "")
        branch_a = str(data.get("branch_a") or data.get("branchA") or data.get("branch") or "")
        branch_b_raw = data.get("branch_b")
        if branch_b_raw is None:
            branch_b_raw = data.get("branchB")
        branch_b = None if branch_b_raw in (None, "") else str(branch_b_raw)

        answer = str(data.get("answer") or data.get("final_answer") or data.get("codellama_response") or "")

        rec = {
            "timestamp": ts,
            "user_question": user_question,
            "is_polish": is_polish,
            "translated_question_en": translated_question_en,
            "consultant": consultant,
            "branchA": branch_a,
            "branchB": branch_b,
            "answer": answer,
        }

        if self._capture_enabled:
            self._jsonl_logger.trace(json.dumps(rec, ensure_ascii=False))  # type: ignore[attr-defined]

        if self._human_enabled:
            lines: List[str] = []
            lines.append("=" * 116)
            lines.append(f"Timestamp: {ts}")
            lines.append("")
            lines.append("User question:")
            lines.append(user_question)
            lines.append("")
            lines.append("Is Polish:")
            lines.append(str(is_polish).lower())
            lines.append("")
            lines.append("Translated (EN):")
            lines.append(translated_question_en if translated_question_en else "(none)")
            lines.append("")
            lines.append("Consultant:")
            lines.append(consultant if consultant else "(none)")
            lines.append("")
            lines.append("BranchA:")
            lines.append(branch_a if branch_a else "(none)")
            lines.append("")
            lines.append("BranchB:")
            lines.append(branch_b if branch_b else "(none)")
            lines.append("")
            lines.append("Answer:")
            lines.append(answer)
            lines.append("")
            lines.append("JSON:")
            lines.append(json.dumps(rec, ensure_ascii=False))
            lines.append("")
            self._human_logger.info("\n".join(lines))
