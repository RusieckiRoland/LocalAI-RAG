from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def _trace(self: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, msg, args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class LoggingConfig:
    # Base directory for logs.
    log_dir: Path = Path("log")

    # Normal application log.
    app_file: str = "app.log"
    level: str = "INFO"

    # Rotation.
    when: str = "midnight"
    interval: int = 1
    backup_count: int = 14
    also_stdout: bool = False

    # Structured AI interactions (JSONL), 1 record = 1 turn.
    interactions_file: str = "ai_interactions.jsonl"
    interactions_level: str = "TRACE"

    # AI interaction artifacts (doc: logging.ai_interaction.*)
    capture_jsonl: bool = False
    human_log: bool = False
    human_file: str = "ai_interaction.log"

    # Human log localization.
    lang: str = "en"
    locale_dir: Path = Path("locales/ai_interaction")

    # If enabled, emit pointers into app.log.
    emit_app_log_pointers: bool = False


def logging_config_from_runtime_config(runtime_cfg: Dict[str, Any]) -> LoggingConfig:
    """
    Build LoggingConfig from runtime config.json dict.

    Source of truth:
      - runtime_cfg["logging"] (app log + jsonl file name + rotation)
      - runtime_cfg["logging"]["ai_interaction"] (enable flags + human file + i18n)
    """
    root = runtime_cfg.get("logging") or {}
    if not isinstance(root, dict):
        root = {}

    ai = root.get("ai_interaction") or {}
    if not isinstance(ai, dict):
        ai = {}

    return LoggingConfig(
        log_dir=Path(str(root.get("dir") or "log")),
        level=str(root.get("level") or "INFO"),
        interactions_level=str(root.get("interactions_level") or "TRACE"),
        when=str(root.get("when") or "midnight"),
        interval=int(root.get("interval") or 1),
        backup_count=int(root.get("backup_count") or 14),
        also_stdout=bool(root.get("also_stdout") or False),
        app_file=str(root.get("app_file") or "app.log"),
        interactions_file=str(root.get("interactions_file") or "ai_interactions.jsonl"),
        capture_jsonl=bool(ai.get("capture_jsonl") or False),
        human_log=bool(ai.get("human_log") or False),
        human_file=str(ai.get("human_file") or "ai_interaction.log"),
        lang=str(ai.get("lang") or "en"),
        locale_dir=Path(str(ai.get("locale_dir") or "locales/ai_interaction")),
        emit_app_log_pointers=bool(ai.get("emit_app_log_pointers") or False),
    )


def _clear_flagged_handlers(logger: logging.Logger, flag_attr: str) -> None:
    for h in list(logger.handlers):
        if getattr(h, flag_attr, False):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass


def configure_logging(cfg: LoggingConfig) -> None:
    """
    Configure:
      - app log (always enabled)
      - JSONL interactions log (enabled only when cfg.capture_jsonl == True)

    NOTE: config.json is the only source of truth for enable/disable.
    """
    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.level.upper(), logging.INFO))

    # Remove previously attached handlers we own (avoid duplicates in tests / reload).
    _clear_flagged_handlers(root, "_localai_app")
    _clear_flagged_handlers(root, "_localai_stdout")

    app_handler = TimedRotatingFileHandler(
        filename=str(cfg.log_dir / cfg.app_file),
        when=cfg.when,
        interval=int(cfg.interval),
        backupCount=int(cfg.backup_count),
        encoding="utf-8",
        utc=True,
    )
    app_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    setattr(app_handler, "_localai_app", True)
    root.addHandler(app_handler)

    if cfg.also_stdout:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        setattr(sh, "_localai_stdout", True)
        root.addHandler(sh)

    # Structured interactions (JSONL).
    interactions_logger = logging.getLogger("localai.interactions")
    interactions_logger.setLevel(getattr(logging, cfg.interactions_level.upper(), TRACE_LEVEL))
    interactions_logger.propagate = False

    _clear_flagged_handlers(interactions_logger, "_localai_interactions")

    if cfg.capture_jsonl:
        interactions_handler = TimedRotatingFileHandler(
            filename=str(cfg.log_dir / cfg.interactions_file),
            when=cfg.when,
            interval=int(cfg.interval),
            backupCount=int(cfg.backup_count),
            encoding="utf-8",
            utc=True,
        )
        interactions_handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(interactions_handler, "_localai_interactions", True)
        interactions_logger.addHandler(interactions_handler)


class InteractionLogger:
    """
    Doc-compliant AI interaction logger.

    Files (controlled by config.json -> LoggingConfig):
      - JSONL: cfg.interactions_file (enabled by cfg.capture_jsonl)
      - Human: cfg.human_file (enabled by cfg.human_log)

    Compatibility:
      - tests / legacy harness may still call InteractionLogger(<path>) and legacy log_interaction kwargs.
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
                interactions_file=base_cfg.interactions_file,
                interactions_level=base_cfg.interactions_level,
                capture_jsonl=False,           # keep legacy behavior
                human_log=True,                # always on for explicit log file
                human_file=p.name,
                lang=base_cfg.lang,
                locale_dir=base_cfg.locale_dir,
                emit_app_log_pointers=False,
            )

        self._cfg = base_cfg
        self._cfg.log_dir.mkdir(parents=True, exist_ok=True)

        self._capture_enabled = bool(self._cfg.capture_jsonl)
        self._human_enabled = bool(self._cfg.human_log)

        self._lang = (self._cfg.lang or "en").strip().lower()
        self._locale_dir = Path(str(self._cfg.locale_dir or "locales/ai_interaction"))

        self._translations: Dict[str, str] = {}
        if self._lang != "en":
            loc_file = self._locale_dir / f"{self._lang}.json"
            if loc_file.exists():
                try:
                    self._translations = json.loads(loc_file.read_text(encoding="utf-8"))
                except Exception:
                    logging.getLogger("localai").warning(
                        "Failed to read locale file for AI interaction log: %s (fallback to English)",
                        str(loc_file),
                    )
                    self._translations = {}
            else:
                logging.getLogger("localai").warning(
                    "Locale file for AI interaction log not found: %s (fallback to English)",
                    str(loc_file),
                )

        self._app_logger = logging.getLogger("localai")
        self._jsonl_logger = logging.getLogger("localai.interactions")

        # Human log handler is owned here (so it's independently toggleable).
        self._human_logger = logging.getLogger("localai.ai_interaction.human")
        self._human_logger.setLevel(logging.INFO)
        self._human_logger.propagate = False

        if self._human_enabled:
            _clear_flagged_handlers(self._human_logger, "_ai_interaction_human")
            h = TimedRotatingFileHandler(
                filename=str(self._cfg.log_dir / self._cfg.human_file),
                when=self._cfg.when,
                interval=int(self._cfg.interval),
                backupCount=int(self._cfg.backup_count),
                encoding="utf-8",
                utc=True,
            )
            h.setFormatter(logging.Formatter("%(message)s"))
            setattr(h, "_ai_interaction_human", True)
            self._human_logger.addHandler(h)

        # Legacy tests use logger.logger.handlers
        self.logger = self._human_logger

    def _t(self, key: str) -> str:
        return self._translations.get(key, key)

    def _ensure_jsonl_handler_if_needed(self) -> None:
        if not self._capture_enabled:
            return
        # If configure_logging() wasn't called, ensure we still have a handler.
        if any(getattr(h, "_localai_interactions", False) for h in self._jsonl_logger.handlers):
            return

        interactions_handler = TimedRotatingFileHandler(
            filename=str(self._cfg.log_dir / self._cfg.interactions_file),
            when=self._cfg.when,
            interval=int(self._cfg.interval),
            backupCount=int(self._cfg.backup_count),
            encoding="utf-8",
            utc=True,
        )
        interactions_handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(interactions_handler, "_localai_interactions", True)
        self._jsonl_logger.addHandler(interactions_handler)

    def log_interaction(
        self,
        *,
        # Ports signature (preferred)
        session_id: str = "",
        pipeline_name: str = "",
        step_id: str = "",
        action: str = "",
        data: Optional[Dict[str, Any]] = None,
        # Legacy kwargs signature (tests / older runtime)
        original_question: str = "",
        model_input_en: str = "",
        codellama_response: str = "",
        followup_query: Optional[str] = None,
        query_type: Optional[str] = None,
        final_answer: Optional[str] = None,
        context_blocks: Optional[Sequence[str]] = None,
        next_codellama_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ts = _utc_ts()

        if data is None:
            data = {
                "original_question": original_question,
                "model_input_en": model_input_en,
                "codellama_response": codellama_response,
                "followup_query": followup_query,
                "query_type": query_type or "",
                "final_answer": final_answer or "",
                "context_blocks": list(context_blocks or []),
                "next_codellama_prompt": next_codellama_prompt or "",
                "metadata": metadata or {},
            }

        original_question = str(data.get("original_question") or "")
        model_input_en = str(data.get("model_input_en") or "")
        codellama_response = str(data.get("codellama_response") or "")
        followup_query = data.get("followup_query")
        query_type = str(data.get("query_type") or "")
        final_answer = str(data.get("final_answer") or "")
        context_blocks_list = list(data.get("context_blocks") or [])
        next_codellama_prompt = str(data.get("next_codellama_prompt") or "")

        md = data.get("metadata") or {}
        if not isinstance(md, dict):
            md = {"value": md}

        # JSONL capture
        if self._capture_enabled:
            self._ensure_jsonl_handler_if_needed()

            rec = {
                "timestamp": ts,
                "session_id": session_id,
                "pipeline_name": pipeline_name,
                "step_id": step_id,
                "action": action,
                "original_question": original_question,
                "model_input_en": model_input_en,
                "codellama_response": codellama_response,
                "followup_query": followup_query,
                "query_type": query_type,
                "final_answer": final_answer,
                "context_blocks": context_blocks_list,
                "next_codellama_prompt": next_codellama_prompt,
                "metadata": md,
            }
            self._jsonl_logger.trace(json.dumps(rec, ensure_ascii=False))  # type: ignore[attr-defined]

            if bool(self._cfg.emit_app_log_pointers):
                self._app_logger.info(
                    "AI interaction captured (details in %s)",
                    str((self._cfg.log_dir / self._cfg.interactions_file).resolve()),
                )

        # Human-readable
        if self._human_enabled:
            lines: List[str] = []
            lines.append("=" * 116)
            lines.append(f"{self._t('Timestamp')}: {ts}")
            if next_codellama_prompt:
                lines.append(f"{self._t('Prompt')}: {next_codellama_prompt}")
            lines.append("")
            lines.append(self._t("Original question:"))
            lines.append(original_question)
            lines.append("")
            lines.append(self._t("Translated (EN):"))
            lines.append(model_input_en)
            lines.append("")
            lines.append(self._t("CodeLlama replied:"))
            lines.append(codellama_response)
            lines.append("")
            if followup_query:
                lines.append(self._t("Follow-up query:"))
                lines.append(str(followup_query))
                lines.append("")
            lines.append(f"{self._t('Query type')}: {query_type}")
            lines.append("")
            lines.append(self._t("Final answer:"))
            lines.append(final_answer)
            lines.append("")
            lines.append(self._t("Context blocks:"))
            if context_blocks_list:
                for i, block in enumerate(context_blocks_list, start=1):
                    lines.append(f"[{self._t('Context')} {i}]")
                    lines.append(str(block))
                    lines.append("")
            else:
                lines.append("(none)")
                lines.append("")
            if md:
                lines.append(self._t("Metadata:"))
                lines.append(json.dumps(md, ensure_ascii=False, indent=2))
                lines.append("")
            lines.append(self._t("JSON:"))
            lines.append(
                json.dumps(
                    {
                        "timestamp": ts,
                        "original_question": original_question,
                        "model_input_en": model_input_en,
                        "codellama_response": codellama_response,
                        "followup_query": followup_query,
                        "query_type": query_type,
                        "final_answer": final_answer,
                        "context_blocks": context_blocks_list,
                        "next_codellama_prompt": next_codellama_prompt,
                        "metadata": md,
                    },
                    ensure_ascii=False,
                )
            )
            lines.append("")
            self._human_logger.info("\n".join(lines))

            if bool(self._cfg.emit_app_log_pointers):
                self._app_logger.info(
                    "AI interaction human log written (details in %s)",
                    str((self._cfg.log_dir / self._cfg.human_file).resolve()),
                )
