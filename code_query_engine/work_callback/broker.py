from __future__ import annotations

import threading
import time
from queue import Queue
from typing import Any, Dict, List, Optional, Tuple

from .formatter import summarize_trace_event_for_ui
from .policy import (
    CallbackPolicy,
    DEFAULT_CALLBACK_POLICY,
    callback_policy_from_dict,
    callback_policy_to_dict,
)


_MAX_EVENTS_PER_RUN = 600
_RUN_TTL_SEC = 60 * 20


class _TraceRun:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self.queues: List[Queue] = []
        self.closed = False
        self.closed_reason = ""
        self.created_ts = time.time()
        self.last_emit_ts = self.created_ts
        self.policy: CallbackPolicy = DEFAULT_CALLBACK_POLICY


class WorkCallbackBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, _TraceRun] = {}

    def ensure_run(self, run_id: str, *, policy: Optional[CallbackPolicy] = None) -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                run = _TraceRun()
                self._runs[rid] = run
            if policy is not None:
                run.policy = policy
        self._cleanup_locked()

    def configure_run(
        self,
        run_id: str,
        *,
        policy: Optional[CallbackPolicy] = None,
    ) -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                run = _TraceRun()
                self._runs[rid] = run
            if policy is not None:
                run.policy = policy
        self._cleanup_locked()

    def open_stream(self, run_id: str) -> Tuple[Queue, List[Dict[str, Any]], bool, str]:
        rid = (run_id or "").strip()
        if not rid:
            raise ValueError("run_id is required")
        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                run = _TraceRun()
                self._runs[rid] = run
            q: Queue = Queue()
            run.queues.append(q)
            snapshot = list(run.events)
            closed = bool(run.closed)
            reason = run.closed_reason
        self._cleanup_locked()
        return q, snapshot, closed, reason

    def remove_stream(self, run_id: str, q: Queue) -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                return
            run.queues = [x for x in run.queues if x is not q]
        self._cleanup_locked()

    def emit(self, run_id: str, event: Dict[str, Any]) -> None:
        rid = (run_id or "").strip()
        if not rid or not isinstance(event, dict):
            return

        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                run = _TraceRun()
                self._runs[rid] = run
            policy = run.policy

        ui_event = summarize_trace_event_for_ui(event, policy=policy)
        if ui_event is None:
            return

        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                return
            run.last_emit_ts = time.time()
            run.events.append(ui_event)
            if len(run.events) > _MAX_EVENTS_PER_RUN:
                run.events = run.events[-_MAX_EVENTS_PER_RUN:]
            for q in list(run.queues):
                try:
                    q.put(ui_event)
                except Exception:
                    pass
        self._cleanup_locked()

    def close(self, run_id: str, *, reason: str = "done") -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                run = _TraceRun()
                self._runs[rid] = run
            run.closed = True
            run.closed_reason = reason or "done"
            for q in list(run.queues):
                try:
                    q.put({"type": "done", "reason": run.closed_reason})
                except Exception:
                    pass
        self._cleanup_locked()

    def get_run_policy_dict(self, run_id: str) -> Dict[str, Any]:
        rid = (run_id or "").strip()
        if not rid:
            return callback_policy_to_dict(DEFAULT_CALLBACK_POLICY)
        with self._lock:
            run = self._runs.get(rid)
            if run is None:
                return callback_policy_to_dict(DEFAULT_CALLBACK_POLICY)
            return callback_policy_to_dict(run.policy)

    def set_run_policy_dict(self, run_id: str, raw: Optional[Dict[str, Any]]) -> None:
        policy = callback_policy_from_dict(raw)
        self.configure_run(run_id, policy=policy)

    def _cleanup_locked(self) -> None:
        now = time.time()
        stale: List[str] = []
        for rid, run in self._runs.items():
            if run.closed and (now - run.last_emit_ts) > _RUN_TTL_SEC:
                stale.append(rid)
        for rid in stale:
            self._runs.pop(rid, None)


_BROKER = WorkCallbackBroker()


def get_work_callback_broker() -> WorkCallbackBroker:
    return _BROKER

