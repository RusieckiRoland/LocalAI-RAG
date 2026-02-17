# Backward-compatible shim.
# Real implementation moved to code_query_engine.work_callback.
from __future__ import annotations

from typing import Any, Dict, Optional

from code_query_engine.work_callback.broker import get_work_callback_broker
from code_query_engine.work_callback.formatter import summarize_trace_event_for_ui
from code_query_engine.work_callback.policy import DEFAULT_CALLBACK_POLICY


def get_trace_broker():
    return get_work_callback_broker()


def _summarize_trace_event_for_ui(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return summarize_trace_event_for_ui(event, policy=DEFAULT_CALLBACK_POLICY)

