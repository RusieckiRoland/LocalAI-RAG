# code_query_engine/pipeline/actions/base_action.py
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import is_dataclass, asdict
from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState

py_logger = logging.getLogger(__name__)



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
        # Per-step context for inbox enqueue logging (used by PipelineState.enqueue_message).
        try:
            setattr(state, "_current_step_id", step.id)
            setattr(state, "_inbox_enqueued_buffer", [])
        except Exception:
            pass

        # Mandatory: every action consumes its inbox messages at step entry (clear even if unused).
        consumed_msgs = self.consume_inbox_for_step(step, state, runtime)
        try:
            state.inbox_last_consumed = list(consumed_msgs or [])
        except Exception:
            pass

        trace_enabled = self._trace_enabled(runtime)

        in_data: Dict[str, Any] = {}
        if trace_enabled:
            in_data = self._safe_call_log_in(step, state, runtime)
            in_data["_inbox_consume"] = self._consume_summary(step.id, consumed_msgs)

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
                out_data["_inbox_enqueued"] = self._enqueued_summary(getattr(state, "_inbox_enqueued_buffer", None))
                event = {
                    "ts_utc": self._utc_ts(),
                    "t_ms": int(time.time() * 1000),
                    "step": {
                        "id": step.id,
                        "action": step.action,
                        "next_default": step.next,
                        "next_resolved": resolved_next,
                        "stages_visible": self._stages_visible_flag(step),
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
                labels = self._callback_labels(step)
                if labels:
                    event["callback"] = labels
                self._append_trace_event(state, event)
            # Ensure per-step temporary buffers don't leak across steps.
            try:
                setattr(state, "_inbox_enqueued_buffer", [])
                setattr(state, "_current_step_id", None)
            except Exception:
                pass

        return next_override

    # -------------------------
    # Helpers
    # -------------------------

    def consume_inbox_for_step(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> List[Dict[str, Any]]:
        """
        Virtual inbox consumer (default: select by target_step_id == step.id, then remove).
        Returns the consumed messages (actions may inspect state.inbox_last_consumed).
        """
        consumed: List[Dict[str, Any]] = []
        try:
            fn = getattr(state, "consume_inbox_for_step", None)
            if callable(fn):
                consumed = list(fn(step_id=step.id) or [])
            else:
                # Soft fallback for older PipelineState versions.
                inbox = list(getattr(state, "inbox", []) or [])
                keep: List[Dict[str, Any]] = []
                for msg in inbox:
                    if str((msg or {}).get("target_step_id") or "").strip() == step.id:
                        consumed.append(msg)
                    else:
                        keep.append(msg)
                setattr(state, "inbox", keep)
        except Exception:
            py_logger.exception("soft-failure: consume_inbox_for_step failed")
            consumed = []

        # Record a CONSUME trace event (deterministic, even if count=0).
        try:
            run_id = getattr(state, "pipeline_run_id", None)
            evt = {
                "event_type": "CONSUME",
                "ts_utc": self._utc_ts(),
                "t_ms": int(time.time() * 1000),
                "run_id": run_id,
                "session_id": getattr(state, "session_id", None),
                "pipeline_name": getattr(state, "pipeline_name", None),
                "consumer_step_id": step.id,
                "stages_visible": self._stages_visible_flag(step),
                **self._consume_summary(step.id, consumed),
            }
            labels = self._callback_labels(step)
            if labels:
                evt["callback"] = labels
            self._append_trace_event(state, evt)
        except Exception:
            pass

        return consumed

    def _trace_enabled(self, runtime: PipelineRuntime) -> bool:
        v = (os.getenv("RAG_PIPELINE_TRACE") or "").strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        # Optional: allow runtime to force it (non-breaking if missing)
        if bool(getattr(runtime, "pipeline_trace_enabled", False)):
            return True
        return False

    def _full_trace_allowed(self, runtime: PipelineRuntime) -> bool:
        """
        Full trace (rendered prompts/chat/context) is allowed only in development.
        """
        env = (os.getenv("APP_DEVELOPMENT") or "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            return True
        if env in ("0", "false", "no", "off"):
            return False
        settings = getattr(runtime, "pipeline_settings", None) or {}
        if isinstance(settings, dict):
            if "development" in settings:
                return bool(settings.get("development"))
            if "developement" in settings:
                return bool(settings.get("developement"))
        return False

    def _append_trace_event(self, state: PipelineState, event: Dict[str, Any]) -> None:
        if "run_id" not in event:
            try:
                rid = getattr(state, "pipeline_run_id", None)
                if rid:
                    event["run_id"] = rid
            except Exception:
                pass
        lst = getattr(state, "pipeline_trace_events", None)
        if lst is None:
            lst = []
            setattr(state, "pipeline_trace_events", lst)
        lst.append(event)

    def _stages_visible_flag(self, step: StepDef) -> Optional[bool]:
        try:
            raw = getattr(step, "raw", {}) or {}
            if "stages_visible" not in raw:
                return None
            return bool(raw.get("stages_visible"))
        except Exception:
            return None

    def _safe_call_log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        try:
            data = self.log_in(step, state, runtime) or {}
            return self._jsonable(data)
        except Exception as ex:
            py_logger.exception("soft-failure: log_in failed; returning minimal trace event")
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
            py_logger.exception("soft-failure: log_out failed; returning minimal trace event")
            return {"_log_out_error": {"type": ex.__class__.__name__, "message": str(ex)}}

    def _utc_ts(self) -> str:
        # Avoid importing datetime for speed; ISO-ish is enough
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _consume_summary(self, consumer_step_id: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        for m in (messages or []):
            if not isinstance(m, dict):
                continue
            topic = str(m.get("topic") or "").strip()
            payload = m.get("payload") if isinstance(m.get("payload"), dict) else None
            items.append({"topic": topic, "payload_summary": self._payload_summary(payload)})
        return {"consumer_step_id": consumer_step_id, "count": len(items), "messages": items}

    def _enqueued_summary(self, enqueued: Any) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        if isinstance(enqueued, list):
            for m in enqueued:
                if not isinstance(m, dict):
                    continue
                items.append(
                    {
                        "target_step_id": str(m.get("target_step_id") or "").strip(),
                        "topic": str(m.get("topic") or "").strip(),
                        "payload_summary": self._payload_summary(m.get("payload") if isinstance(m.get("payload"), dict) else None),
                    }
                )
        return {"count": len(items), "messages": items}

    def _payload_summary(self, payload: Optional[Dict[str, Any]], *, max_len: int = 400) -> str:
        if payload is None:
            return ""
        try:
            import json

            s = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            s = repr(payload)
        if len(s) > max_len:
            return s[: max_len - 3] + "..."
        return s

    def _callback_labels(self, step: StepDef) -> Dict[str, str]:
        raw = getattr(step, "raw", None)
        if not isinstance(raw, dict):
            return {}
        caption = str(raw.get("callback_caption") or "").strip()
        caption_translated = str(raw.get("callback_caption_translated") or "").strip()
        out: Dict[str, str] = {}
        if caption:
            out["caption"] = caption
        if caption_translated:
            out["caption_translated"] = caption_translated
        return out

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
