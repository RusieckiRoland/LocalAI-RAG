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
    answer_translated: Optional[str]

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
        trace_events_enabled = trace_file_enabled or (os.getenv("RAG_PIPELINE_TRACE") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        trace_events_enabled = trace_events_enabled or bool(getattr(runtime, "pipeline_trace_enabled", False))

        if trace_events_enabled:
            # Stable-ish run id for correlating ENQUEUE/CONSUME/RUN_END across one PipelineEngine.run().
            try:
                session_id = getattr(state, "session_id", None) or "no-session"
                pipeline_name = getattr(state, "pipeline_name", None) or pipeline.name or "no-pipeline"
                safe_session = str(session_id).replace("/", "_").replace("\\", "_").replace(" ", "_")
                safe_pipeline = str(pipeline_name).replace("/", "_").replace("\\", "_").replace(" ", "_")
                run_id = getattr(state, "pipeline_run_id", None)
                if not run_id:
                    run_id = f"{int(time.time() * 1000)}_{safe_session}_{safe_pipeline}"
                    setattr(state, "pipeline_run_id", run_id)
            except Exception:
                pass

            if getattr(state, "pipeline_trace_events", None) is None:
                setattr(state, "pipeline_trace_events", [])

        if trace_file_enabled:
            # Some actions may check runtime.pipeline_trace_enabled to decide if they should record events.
            # We set it dynamically to avoid changing PipelineRuntime signature.
            setattr(runtime, "pipeline_trace_enabled", True)

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

            # Policy: fail-fast if inbox is not empty at run end (recommended for tests).
            fail_fast = (os.getenv("RAG_PIPELINE_INBOX_FAIL_FAST") or "").strip().lower() in ("1", "true", "yes", "on")
            remaining = list(getattr(state, "inbox", []) or [])
            if remaining and fail_fast:
                raise RuntimeError(
                    f"PIPELINE_INBOX_NOT_EMPTY: remaining={len(remaining)} (set RAG_PIPELINE_INBOX_FAIL_FAST=0 to log-only)"
                )

            # Resolve final answer (what the caller sees)
            final_answer = getattr(state, "answer_en", None) or ""
            if bool(getattr(state, "translate_chat", False)) and getattr(state, "answer_translated", None):
                final_answer = state.answer_translated

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
                answer_translated=getattr(state, "answer_translated", None),
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
            # Always emit RUN_END trace event when tracing is enabled (even on errors).
            if trace_events_enabled:
                inbox_remaining = list(getattr(state, "inbox", []) or [])
                rem_pairs: List[Dict[str, str]] = []
                for m in inbox_remaining:
                    if not isinstance(m, dict):
                        continue
                    rem_pairs.append(
                        {
                            "target_step_id": str(m.get("target_step_id") or "").strip(),
                            "topic": str(m.get("topic") or "").strip(),
                        }
                    )
                evt = {
                    "event_type": "RUN_END",
                    "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "t_ms": int(time.time() * 1000),
                    "run_id": getattr(state, "pipeline_run_id", None),
                    "session_id": getattr(state, "session_id", None),
                    "pipeline_name": getattr(state, "pipeline_name", None),
                    "inbox_remaining_count": len(inbox_remaining),
                    "inbox_remaining": rem_pairs,
                }
                try:
                    events = getattr(state, "pipeline_trace_events", None)
                    if events is None:
                        events = []
                        setattr(state, "pipeline_trace_events", events)
                    events.append(evt)
                except Exception:
                    pass

            if trace_file_enabled:
                # Write one JSON file per interaction (per PipelineEngine.run()).
                trace_dir = (os.getenv("RAG_PIPELINE_TRACE_DIR") or "").strip()
                if not trace_dir:
                    if (os.getenv("RUN_INTEGRATION_TESTS") or "").strip() == "1":
                        trace_dir = "log/integration/retrival/pipeline_traces"
                    else:
                        trace_dir = "log/pipeline_traces"
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
                    "run_id": getattr(state, "pipeline_run_id", None),
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
                    "answer_translated": getattr(state, "answer_translated", None),
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

                # Deterministic JSONL (one event per line) for easier grep/streaming.
                try:
                    events = list(getattr(state, "pipeline_trace_events", []) or [])
                    jsonl_name = filename.replace(".json", ".jsonl")
                    jsonl_path = Path(trace_dir) / jsonl_name
                    tmp_jsonl = str(jsonl_path) + ".tmp"
                    with open(tmp_jsonl, "w", encoding="utf-8") as f:
                        for ev in events:
                            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                    os.replace(tmp_jsonl, jsonl_path)

                    latest_jsonl = Path(trace_dir) / "latest.jsonl"
                    tmp_latest_jsonl = str(latest_jsonl) + ".tmp"
                    with open(tmp_latest_jsonl, "w", encoding="utf-8") as f:
                        for ev in events:
                            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                    os.replace(tmp_latest_jsonl, latest_jsonl)
                except Exception:
                    py_logger.exception("soft-failure: failed to write pipeline trace JSONL")
