# code_query_engine/pipeline/actions/base_action.py
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import is_dataclass, asdict
from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState


class PipelineActionBase(ABC):
    """
    Base class for pipeline actions with mandatory structured tracing.

    Enable tracing with env var:
        RAG_PIPELINE_TRACE=1

    When enabled, each action appends one JSON-serializable event to:
        state.pipeline_trace_events (List[dict])
    """

    # -------------------------
    # Required action identity
    # -------------------------

    @property
    @abstractmethod
    def action_id(self) -> str:
        """
        Logical action identifier (should match registry key / YAML 'action', e.g. 'call_model').
        """
        raise NotImplementedError

    # -------------------------
    # Required per-action logs
    # -------------------------

    @abstractmethod
    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def log_out(
        self,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
        *,
        next_step_id: Optional[str],
        error: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        raise NotImplementedError

    # -------------------------
    # Required step logic
    # -------------------------

    @abstractmethod
    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raise NotImplementedError

    # -------------------------
    # Public entrypoint (engine calls this)
    # -------------------------

    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        trace_enabled = self._trace_enabled(runtime)

        in_data: Dict[str, Any] = {}
        if trace_enabled:
            in_data = self._safe_call_log_in(step, state, runtime)

        error: Optional[Dict[str, Any]] = None
        next_override: Optional[str] = None

        try:
            next_override = self.do_execute(step, state, runtime)
        except Exception as ex:
            error = {
                "type": ex.__class__.__name__,
                "message": str(ex),
            }
            raise
        finally:
            resolved_next = next_override or step.next
            if trace_enabled:
                out_data = self._safe_call_log_out(step, state, runtime, next_step_id=resolved_next, error=error)
                event = {
                    "ts_utc": self._utc_ts(),
                    "t_ms": int(time.time() * 1000),
                    "step": {
                        "id": step.id,
                        "action": step.action,
                        "next_default": step.next,
                        "next_resolved": resolved_next,
                    },
                    "action": {
                        "class": self.__class__.__name__,
                        "action_id": self.action_id,
                    },
                    "in": in_data,
                    "out": out_data,
                    "error": error,
                    "state_after": self._jsonable_state(state),
                }
                self._append_trace_event(state, event)

        return next_override

    # -------------------------
    # Helpers
    # -------------------------

    def _trace_enabled(self, runtime: PipelineRuntime) -> bool:
        v = (os.getenv("RAG_PIPELINE_TRACE") or "").strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        # Optional: allow runtime to force it (non-breaking if missing)
        if bool(getattr(runtime, "pipeline_trace_enabled", False)):
            return True
        return False

    def _append_trace_event(self, state: PipelineState, event: Dict[str, Any]) -> None:
        lst = getattr(state, "pipeline_trace_events", None)
        if lst is None:
            lst = []
            setattr(state, "pipeline_trace_events", lst)
        lst.append(event)

    def _safe_call_log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        try:
            data = self.log_in(step, state, runtime) or {}
            return self._jsonable(data)
        except Exception as ex:
            return {"_log_in_error": {"type": ex.__class__.__name__, "message": str(ex)}}

    def _safe_call_log_out(
        self,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
        *,
        next_step_id: Optional[str],
        error: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        try:
            data = self.log_out(step, state, runtime, next_step_id=next_step_id, error=error) or {}
            return self._jsonable(data)
        except Exception as ex:
            return {"_log_out_error": {"type": ex.__class__.__name__, "message": str(ex)}}

    def _utc_ts(self) -> str:
        # Avoid importing datetime for speed; ISO-ish is enough
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _jsonable_state(self, state: PipelineState) -> Dict[str, Any]:
        # PipelineState is a dataclass in this repo; keep fallback safe anyway.
        if is_dataclass(state):
            return self._jsonable(asdict(state))
        return self._jsonable(getattr(state, "__dict__", {}))

    def _jsonable(self, obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            out: Dict[str, Any] = {}
            for k, v in obj.items():
                out[str(k)] = self._jsonable(v)
            return out
        if isinstance(obj, (list, tuple)):
            return [self._jsonable(x) for x in obj]
        if isinstance(obj, set):
            return [self._jsonable(x) for x in sorted(obj, key=lambda t: str(t))]
        # dataclass-like objects
        if is_dataclass(obj):
            return self._jsonable(asdict(obj))
        # fallback: repr (keeps it serializable and "complete enough")
        try:
            return repr(obj)
        except Exception:
            return "<unrepr-able>"
