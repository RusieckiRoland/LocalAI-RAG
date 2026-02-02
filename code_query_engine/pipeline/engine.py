# code_query_engine/pipeline/engine.py
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .action_registry import ActionRegistry
from .definitions import PipelineDef, StepDef
from .providers.ports import (
    IGraphProvider,
    IHistoryManager,
    IInteractionLogger,
    IMarkdownTranslatorEnPl,
    IModelClient,
    IRetriever,
    ITokenCounter,
    ITranslatorPlEn,
    IRetrievalBackend,
)

py_logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    # Execution
    steps_used: int
    step_trace: List[str]

    # Answers (expected by tests)
    answer_en: Optional[str]
    answer_pl: Optional[str]

    # Final view
    final_answer: str
    query_type: str
    model_input_en: str


class PipelineRuntime:
    """
    Runtime DI container expected by existing actions and tests.

    IMPORTANT:
    - Retrieval contract uses `retrieval_backend` (strict).
    - Legacy dispatcher wiring was removed (Weaviate-only, single retrieval entrypoint).
    """

    def __init__(
        self,
        *,
        pipeline_settings: Dict[str, Any],
        model: Optional[IModelClient],
        searcher: Optional[IRetriever],
        markdown_translator: Optional[IMarkdownTranslatorEnPl],
        translator_pl_en: Optional[ITranslatorPlEn],
        history_manager: Optional[IHistoryManager],
        logger: Optional[IInteractionLogger],
        constants: Any,
        retrieval_backend: Optional[IRetrievalBackend] = None,
        graph_provider: Optional[IGraphProvider] = None,
        token_counter: Optional[ITokenCounter] = None,
        add_plant_link: Optional[Any] = None,
    ) -> None:
        self.pipeline_settings = pipeline_settings or {}
        self.model = model

        # NOTE: kept for now because some call sites still pass it.
        # It will be removed once all actions use retrieval_backend only.
        self.searcher = searcher

        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.history_manager = history_manager
        self.logger = logger
        self.constants = constants

        # New contract: retrieval backend (required by retrieval_contract)
        self.retrieval_backend = retrieval_backend

        self.graph_provider = graph_provider
        self.token_counter = token_counter

        # Some call sites pass add_plant_link=lambda text, consultant=None: text
        self.add_plant_link = add_plant_link or (lambda x, consultant=None: x)

    # ---------------------------------------------------------------------
    # Strict retrieval contract entrypoint
    # ---------------------------------------------------------------------
    def get_retrieval_backend(self) -> IRetrievalBackend:
        if self.retrieval_backend is None:
            raise ValueError("PipelineRuntime: retrieval_backend is required by retrieval_contract")
        return self.retrieval_backend


class PipelineEngine:
    """
    Executes steps sequentially. Action decides branching by returning next step id.
    If action returns None, engine follows step.next. If step.end==True => stop.
    """

    def __init__(self, actions: Optional[ActionRegistry] = None, *, registry: Optional[ActionRegistry] = None) -> None:
        # Backward-compat: tests use PipelineEngine(registry=...)
        self._actions = registry or actions
        if self._actions is None:
            raise ValueError("PipelineEngine requires an ActionRegistry instance.")

    def run(self, pipeline: PipelineDef, state: Any, runtime: PipelineRuntime) -> PipelineResult:
        settings = pipeline.settings or {}
        current_step_id = (settings.get("entry_step_id") or "").strip()
        if not current_step_id:
            raise ValueError("Pipeline settings must define 'entry_step_id'.")

        steps_by_id = pipeline.steps_by_id()

        state.pipeline_name = pipeline.name
        state.steps_used = 0
        state.step_trace = []

        # Enable per-interaction trace file in dev via env flag.
        # This flag also enables in-memory step events produced by actions.
        trace_file_enabled = (os.getenv("RAG_PIPELINE_TRACE_FILE") or "").strip().lower() in ("1", "true", "yes", "on")
        if trace_file_enabled:
            # Some actions may check runtime.pipeline_trace_enabled to decide if they should record events.
            # We set it dynamically to avoid changing PipelineRuntime signature.
            setattr(runtime, "pipeline_trace_enabled", True)

            # Ensure the event list exists even if some actions don't append anything.
            if getattr(state, "pipeline_trace_events", None) is None:
                setattr(state, "pipeline_trace_events", [])

        # We want to write a JSON file even if the pipeline raises.
        trace_error: Optional[Dict[str, Any]] = None
        final_answer: str = ""
        result: Optional[PipelineResult] = None

        try:
            while current_step_id:
                step: StepDef = steps_by_id.get(current_step_id)  # type: ignore[assignment]
                if step is None:
                    raise KeyError(f"Unknown step id: '{current_step_id}'")

                state.steps_used += 1
                state.step_trace.append(current_step_id)

                action = self._actions.get(step.action)

                # Actions in repo are mixed: some use positional, some keyword-only.
                next_step_id: Optional[str]
                try:
                    next_step_id = action.execute(step, state, runtime)  # type: ignore[attr-defined]
                except TypeError:
                    next_step_id = action.execute(step=step, state=state, runtime=runtime)  # type: ignore[attr-defined]

                # stop if this step is terminal
                if bool(step.end):
                    break

                # action override
                if next_step_id:
                    current_step_id = next_step_id
                    continue

                # default next from YAML
                if step.next:
                    current_step_id = step.next
                    continue

                break

            # Resolve final answer (what the caller sees)
            final_answer = getattr(state, "answer_en", None) or ""
            if bool(getattr(state, "translate_chat", False)) and getattr(state, "answer_pl", None):
                final_answer = state.answer_pl

            state.final_answer = final_answer

            # Some tests rely on this helper existing; keep it defensive.
            model_input_en = ""
            try:
                model_input_en = state.model_input_en_or_fallback()
            except Exception:
                model_input_en = getattr(state, "model_input_en", None) or ""

            result = PipelineResult(
                steps_used=state.steps_used,
                step_trace=list(state.step_trace),
                answer_en=getattr(state, "answer_en", None),
                answer_pl=getattr(state, "answer_pl", None),
                final_answer=final_answer,
                query_type=getattr(state, "query_type", None) or "",
                model_input_en=model_input_en,
            )
            return result

        except Exception as ex:
            # Capture the error for trace file, then re-raise.
            trace_error = {
                "type": ex.__class__.__name__,
                "message": str(ex),
            }
            raise

        finally:
            if trace_file_enabled:
                # Write one JSON file per interaction (per PipelineEngine.run()).
                trace_dir = (os.getenv("RAG_PIPELINE_TRACE_DIR") or "logs/pipeline_traces").strip()
                Path(trace_dir).mkdir(parents=True, exist_ok=True)

                ts_ms = int(time.time() * 1000)
                ts_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

                # Make filename safe for filesystem.
                session_id = getattr(state, "session_id", None) or "no-session"
                pipeline_name = getattr(state, "pipeline_name", None) or pipeline.name or "no-pipeline"
                safe_session = str(session_id).replace("/", "_").replace("\\", "_").replace(" ", "_")
                safe_pipeline = str(pipeline_name).replace("/", "_").replace("\\", "_").replace(" ", "_")
                ts_utc_safe = ts_utc.replace("T", "_").replace(":", "-")
                filename = f"{ts_utc_safe}_{ts_ms}_interaction_{safe_session}_{safe_pipeline}.json"
                path = Path(trace_dir) / filename

                # Some tests rely on this helper existing; keep it defensive.
                model_input_en = ""
                try:
                    model_input_en = state.model_input_en_or_fallback()
                except Exception:
                    model_input_en = getattr(state, "model_input_en", None) or ""

                payload: Dict[str, Any] = {
                    "ts_utc": ts_utc,
                    "ts_ms": ts_ms,
                    "session_id": getattr(state, "session_id", None),
                    "pipeline_name": getattr(state, "pipeline_name", None),
                    "entry_step_id": (settings.get("entry_step_id") or "").strip(),
                    "steps_used": getattr(state, "steps_used", None),
                    "step_trace": list(getattr(state, "step_trace", []) or []),
                    "user_query": getattr(state, "user_query", None),
                    "translate_chat": bool(getattr(state, "translate_chat", False)),
                    "model_input_en": (result.model_input_en if result is not None else model_input_en),
                    "answer_en": getattr(state, "answer_en", None),
                    "answer_pl": getattr(state, "answer_pl", None),
                    "final_answer": (
                        result.final_answer
                        if result is not None
                        else (getattr(state, "final_answer", None) or final_answer)
                    ),
                    "query_type": getattr(state, "query_type", None),
                    "error": trace_error,
                    # This is populated by actions via their log_in/log_out hooks.
                    "events": list(getattr(state, "pipeline_trace_events", []) or []),
                }

                # Atomic write: temp file + replace.
                tmp_path = str(path) + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)

                latest_path = Path(trace_dir) / "latest.json"
                tmp_latest = str(latest_path) + ".tmp"
                with open(tmp_latest, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp_latest, latest_path)
