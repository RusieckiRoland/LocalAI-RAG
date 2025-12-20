from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def _trace(self: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, msg, args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]


def _is_truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zip_rotated_log(path: Path) -> None:
    # Zip only plain rotated files, do not re-zip .gz
    if not path.exists() or path.suffix == ".gz":
        return
    gz_path = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    path.unlink(missing_ok=True)


@dataclass(frozen=True)
class LoggingConfig:
    log_dir: Path = Path("log")
    app_log_name: str = "app.log"

    # JSONL, one record per interaction
    interactions_log_name: str = "ai_interactions.jsonl"

    # Human-readable continuous log
    interaction_text_log_name: str = "ai_interaction.log"

    # Default levels
    app_level: str = "INFO"
    interactions_level: str = "TRACE"

    # Rotation
    when: str = "midnight"
    backup_count: int = 14


def configure_logging(cfg: LoggingConfig) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.app_level.upper(), logging.INFO))

    # Root handler (app.log)
    app_handler = TimedRotatingFileHandler(
        filename=str(cfg.log_dir / cfg.app_log_name),
        when=cfg.when,
        backupCount=cfg.backup_count,
        encoding="utf-8",
        utc=True,
    )
    app_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    app_handler.namer = lambda name: name  # keep original naming
    app_handler.rotator = lambda source, dest: shutil.move(source, dest)
    root.addHandler(app_handler)

    # After rotation, zip old logs (best-effort)
    # (We can't hook directly into handler rotation without subclassing; keep it simple:
    # you can call _zip_rotated_log from maintenance script if needed.)

    # Interactions logger (JSONL)
    interactions_logger = logging.getLogger("localai.interactions")
    interactions_logger.setLevel(getattr(logging, cfg.interactions_level.upper(), TRACE_LEVEL))
    interactions_logger.propagate = False

    interactions_handler = TimedRotatingFileHandler(
        filename=str(cfg.log_dir / cfg.interactions_log_name),
        when=cfg.when,
        backupCount=cfg.backup_count,
        encoding="utf-8",
        utc=True,
    )
    interactions_handler.setFormatter(logging.Formatter("%(message)s"))
    interactions_logger.addHandler(interactions_handler)


class InteractionLogger:
    """
    Single entry point used by runtime.
    - JSONL (structured) is controlled by AI_INTERACTION_CAPTURE
    - Human-readable text is controlled by AI_INTERACTION_HUMAN_LOG
    - Language is controlled by AI_INTERACTION_LANG + AI_INTERACTION_LOCALE_DIR
    """

    def __init__(self, *, cfg: Optional[LoggingConfig] = None) -> None:
        self._cfg = cfg or LoggingConfig()
        self._cfg.log_dir.mkdir(parents=True, exist_ok=True)

        self._capture_enabled = _is_truthy(os.getenv("AI_INTERACTION_CAPTURE"))
        self._human_enabled = _is_truthy(os.getenv("AI_INTERACTION_HUMAN_LOG"))

        self._lang = (os.getenv("AI_INTERACTION_LANG") or "en").strip().lower()
        self._locale_dir = Path(os.getenv("AI_INTERACTION_LOCALE_DIR") or "locales/ai_interaction")

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

        # Human log file handler (continuous)
        self._human_logger = logging.getLogger("localai.ai_interaction_text")
        self._human_logger.setLevel(logging.INFO)
        self._human_logger.propagate = False

        if self._human_enabled:
            text_path = self._cfg.log_dir / self._cfg.interaction_text_log_name
            if not any(getattr(h, "_ai_interaction_text", False) for h in self._human_logger.handlers):
                text_path.parent.mkdir(parents=True, exist_ok=True)
                text_path.touch(exist_ok=True)
                h = logging.FileHandler(str(text_path), encoding="utf-8")
                h.setFormatter(logging.Formatter("%(message)s"))
                setattr(h, "_ai_interaction_text", True)
                self._human_logger.addHandler(h)

        self._interactions_logger = logging.getLogger("localai.interactions")
        self._app_logger = logging.getLogger("localai")

    def _t(self, key: str) -> str:
        return self._translations.get(key, key)

    def log_interaction(
        self,
        *,
        original_question: str,
        model_input_en: str,
        codellama_response: str,
        followup_query: Optional[str],
        query_type: str,
        final_answer: str,
        context_blocks: List[str],
        next_codellama_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata = metadata or {}

        # 1) JSONL (structured) — only if enabled by flag
        if self._capture_enabled:
            payload: Dict[str, Any] = {
                "ts": _utc_ts(),
                "prompt": next_codellama_prompt,
                "original_question": original_question,
                "model_input_en": model_input_en,
                "codellama_response": codellama_response,
                "followup_query": followup_query,
                "query_type": query_type,
                "final_answer": final_answer,
                "context_blocks_count": len(context_blocks),
                "metadata": metadata,
            }
            self._interactions_logger.trace(json.dumps(payload, ensure_ascii=False))  # type: ignore[attr-defined]

            # Normal log “pointer” (as agreed)
            self._app_logger.info(
                "AI interaction captured (details in %s)",
                str(self._cfg.log_dir / self._cfg.interactions_log_name),
            )

        # 2) Human-readable text — only if enabled by flag
        if self._human_enabled:
            lines: List[str] = []
            lines.append("=" * 80)
            lines.append(f"{self._t('Timestamp')}: {_utc_ts()}")
            lines.append(f"{self._t('Prompt')}: {next_codellama_prompt}")
            lines.append("")
            lines.append(self._t("Original question"))
            lines.append(original_question)
            lines.append("")
            lines.append(self._t("Translated (EN)"))
            lines.append(model_input_en)
            lines.append("")
            lines.append(self._t("CodeLlama replied"))
            lines.append(codellama_response)
            lines.append("")
            if followup_query:
                lines.append(self._t("Follow-up query"))
                lines.append(followup_query)
                lines.append("")
            lines.append(f"{self._t('Query type')}: {query_type}")
            lines.append("")
            lines.append(self._t("Final answer"))
            lines.append(final_answer)
            lines.append("")
            lines.append(self._t("Context blocks"))
            for i, block in enumerate(context_blocks, start=1):
                lines.append(f"[{self._t('Context')} {i}]")
                lines.append(block)
            if metadata:
                lines.append("")
                lines.append(self._t("Metadata"))
                lines.append(json.dumps(metadata, ensure_ascii=False, indent=2))
            lines.append("")
            lines.append(self._t("JSON"))
            lines.append(
                json.dumps(
                    {
                        "ts": _utc_ts(),
                        "prompt": next_codellama_prompt,
                        "original_question": original_question,
                        "model_input_en": model_input_en,
                        "codellama_response": codellama_response,
                        "followup_query": followup_query,
                        "query_type": query_type,
                        "final_answer": final_answer,
                        "context_blocks_count": len(context_blocks),
                        "metadata": metadata,
                    },
                    ensure_ascii=False,
                )
            )
            self._human_logger.info("\n".join(lines))

            # Normal log “pointer” to the human file too (still only if enabled)
            self._app_logger.info(
                "AI interaction human log written (details in %s)",
                str(self._cfg.log_dir / self._cfg.interaction_text_log_name),
            )
