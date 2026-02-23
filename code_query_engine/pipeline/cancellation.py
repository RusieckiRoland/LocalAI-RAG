from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable


_CANCEL_TTL_SEC = 60 * 20


@dataclass
class CancelRecord:
    ts: float
    reason: str


class PipelineCancelled(Exception):
    def __init__(self, run_id: str, reason: str) -> None:
        super().__init__(f"Pipeline cancelled: {run_id} ({reason})")
        self.run_id = run_id
        self.reason = reason


class PipelineCancelRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: Dict[str, CancelRecord] = {}

    def request_cancel(self, run_id: str, *, reason: str = "cancelled") -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._lock:
            self._items[rid] = CancelRecord(ts=time.time(), reason=reason or "cancelled")
        self._cleanup_locked()

    def is_cancelled(self, run_id: str) -> bool:
        rid = (run_id or "").strip()
        if not rid:
            return False
        with self._lock:
            return rid in self._items

    def get_reason(self, run_id: str) -> Optional[str]:
        rid = (run_id or "").strip()
        if not rid:
            return None
        with self._lock:
            rec = self._items.get(rid)
            return rec.reason if rec else None

    def clear(self, run_id: str) -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._lock:
            self._items.pop(rid, None)
        self._cleanup_locked()

    def _cleanup_locked(self) -> None:
        now = time.time()
        stale = [rid for rid, rec in self._items.items() if (now - rec.ts) > _CANCEL_TTL_SEC]
        for rid in stale:
            self._items.pop(rid, None)


_REGISTRY = PipelineCancelRegistry()


def get_pipeline_cancel_registry() -> PipelineCancelRegistry:
    return _REGISTRY


def append_cancel_event(state: Any, *, run_id: str, reason: str) -> None:
    try:
        if getattr(state, "_cancel_event_emitted", False):
            return
        evt = {
            "event_type": "CANCELLED",
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "t_ms": int(time.time() * 1000),
            "run_id": str(run_id),
            "step": {"id": "cancelled"},
            "action": {"action_id": "cancelled"},
            "callback": {
                "caption": "Cancelled",
                "caption_translated": "Przerwano",
            },
            "out": {"reason": reason},
        }
        events = getattr(state, "pipeline_trace_events", None)
        if events is None:
            events = []
            setattr(state, "pipeline_trace_events", events)
        events.append(evt)
        setattr(state, "_cancel_event_emitted", True)
    except Exception:
        pass


def make_cancel_check(state: Any) -> Optional[Callable[[], None]]:
    run_id = getattr(state, "pipeline_run_id", None)
    if not run_id:
        return None
    registry = get_pipeline_cancel_registry()
    rid = str(run_id)

    def _check() -> None:
        if not registry.is_cancelled(rid):
            return
        reason = registry.get_reason(rid) or "cancelled"
        append_cancel_event(state, run_id=rid, reason=reason)
        raise PipelineCancelled(rid, reason)

    return _check
