# code_query_engine/pipeline/engine.py
from __future__ import annotations

import logging
from dataclasses import dataclass
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
)

from .providers.retrieval import RetrievalDispatcher
import json
import os
import time
from pathlib import Path

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
    """

    def __init__(
        self,
        *,
        pipeline_settings: Dict[str, Any],
        main_model: IModelClient,
        searcher: Optional[IRetriever],
        markdown_translator: Optional[IMarkdownTranslatorEnPl],
        translator_pl_en: Optional[ITranslatorPlEn],
        history_manager: IHistoryManager,
        logger: IInteractionLogger,
        constants: Any,
        retrieval_dispatcher: Optional[RetrievalDispatcher] = None,
        bm25_searcher: Optional[IRetriever] = None,
        semantic_rerank_searcher: Optional[IRetriever] = None,
        graph_provider: Optional[IGraphProvider] = None,
        token_counter: Optional[ITokenCounter] = None,
        add_plant_link: Optional[Any] = None,
    ) -> None:
        self.pipeline_settings = pipeline_settings or {}
        self.main_model = main_model
        self.searcher = searcher
        self.markdown_translator = markdown_translator
        self.translator_pl_en = translator_pl_en
        self.history_manager = history_manager
        self.logger = logger
        self.constants = constants

        self.retrieval_dispatcher = retrieval_dispatcher
        self.bm25_searcher = bm25_searcher
        self.semantic_rerank_searcher = semantic_rerank_searcher

        self.graph_provider = graph_provider
        self.token_counter = token_counter
        self.add_plant_link = add_plant_link or (lambda x: x)

        # Useful debug
        self.last_model_output: Optional[str] = None

    def get_retrieval_dispatcher(self) -> RetrievalDispatcher:
        if self.retrieval_dispatcher is not None:
            return self.retrieval_dispatcher

        semantic_rerank = self.semantic_rerank_searcher
        if semantic_rerank is None and self.searcher is not None:
            # Default reranker over semantic results (works without extra indexes)
            try:
                from common.semantic_rerank_wrapper import SemanticRerankWrapper
                semantic_rerank = SemanticRerankWrapper(self.searcher)
            except Exception:
                py_logger.exception("soft-failure: SemanticRerankWrapper init failed; semantic_rerank disabled")
                semantic_rerank = None

        return RetrievalDispatcher(
            semantic=self.searcher,
            bm25=self.bm25_searcher,
            semantic_rerank=semantic_rerank,
        )



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
            final_answer = state.answer_en or ""
            if getattr(state, "translate_chat", False) and state.answer_pl:
                final_answer = state.answer_pl

            state.final_answer = final_answer

            result = PipelineResult(
                steps_used=state.steps_used,
                step_trace=list(state.step_trace),
                answer_en=state.answer_en,
                answer_pl=state.answer_pl,
                final_answer=final_answer,
                query_type=state.query_type or "",               
                model_input_en=state.model_input_en_or_fallback(),
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
                    "model_input_en": (result.model_input_en if result is not None else state.model_input_en_or_fallback()),
                    "answer_en": getattr(state, "answer_en", None),
                    "answer_pl": getattr(state, "answer_pl", None),
                    "final_answer": (result.final_answer if result is not None else (getattr(state, "final_answer", None) or final_answer)),
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
