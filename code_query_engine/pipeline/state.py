# code_query_engine/pipeline/state.py
from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any, Dict, List, Optional, Set

from ..chat_types import Dialog


@dataclass
class PipelineState:
    # Request identity (EXPECTED BY TESTS)
    user_query: str
    session_id: str
    consultant: str
    request_id: Optional[str] = None
    branch: Optional[str] = None
    translate_chat: bool = False

    # Optional identity
    user_id: Optional[str] = None
    repository: Optional[str] = None
    snapshot_id: Optional[str] = None
    snapshot_id_b: Optional[str] = None
    snapshot_set_id: Optional[str] = None
    snapshot_friendly_names: Dict[str, str] = field(default_factory=dict)
    allowed_commands: List[str] = field(default_factory=list)

    # Router outputs / parse artifacts
    router_raw: Optional[str] = None
    retrieval_mode: str = ""
    retrieval_scope: Optional[str] = None
    retrieval_query: str = ""
    retrieval_filters: Dict[str, Any] = field(default_factory=dict)   
    query_type: Optional[str] = None

    # Retrieval query history within this pipeline run (used to prevent repeats).
    retrieval_queries_asked: List[str] = field(default_factory=list)
    retrieval_queries_asked_norm: Set[str] = field(default_factory=set)

    # Last resolved search execution (for traceability / prompt hygiene).
    last_search_query: Optional[str] = None
    last_search_type: Optional[str] = None
    last_search_filters: Dict[str, Any] = field(default_factory=dict)
    last_search_bm25_operator: Optional[str] = None
    sufficiency_search_mode_constraint: str = ""

    # Materialized node texts 
    node_texts: List[Dict[str, Any]] = field(default_factory=list)

    # Context
    history_dialog: Dialog = field(default_factory=list)
    history_blocks: List[str] = field(default_factory=list)
    history_qa_neutral: Dict[str, str] = field(default_factory=dict)
    context_blocks: List[str] = field(default_factory=list)

    # Model outputs
    
    last_model_response: Optional[str] = None

    # Answer fields expected by multiple actions/engine
    draft_answer_en: Optional[str] = None  
    answer_en: Optional[str] = None
    answer_translated: Optional[str] = None

    # Translation artifacts
    user_question_en: Optional[str] = None
    user_question_pl: Optional[str] = None

    # Diagnostics
    step_trace: List[str] = field(default_factory=list)
    steps_used: int = 0

    # Graph-related (kept for planned dependency expansion)
    retrieval_seed_nodes: List[str] = field(default_factory=list)
    graph_seed_nodes: List[str] = field(default_factory=list)
    graph_expanded_nodes: List[str] = field(default_factory=list)
    graph_edges: List[Dict[str, Any]] = field(default_factory=list)
    graph_debug: Dict[str, Any] = field(default_factory=dict)
    turn_loop_counter: int = 0
    loop_counters: Dict[str, int] = field(default_factory=dict)

    # Final answer (optional convenience)
    final_answer: Optional[str] = None

    # Model input (logged)
    model_input_en: Optional[str] = None

    # Additional: used by some actions/tests
    seen_chunk_ids: Set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Inbox (per-run, memory-only)
    # ------------------------------------------------------------------
    # List of messages with schema:
    #   - target_step_id: str (required)
    #   - topic: str (required)
    #   - payload: dict (optional; JSON-serializable primitives only)
    #
    # Invariant: each new PipelineState starts with an empty inbox.
    inbox: List[Dict[str, Any]] = field(default_factory=list)

    # Overwritten by the engine/base_action on each step entry (convenience for actions).
    inbox_last_consumed: List[Dict[str, Any]] = field(default_factory=list)

    def history_for_prompt(self) -> str:
        parts: List[str] = []
        for msg in (self.history_dialog or []):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip()
            content = str(msg.get("content") or "").strip()
            if not role or not content:
                continue
            parts.append(f"{role}: {content}")
        return "\n\n".join(parts)

    def composed_context_for_prompt(self) -> str:
        blocks: List[str] = []
        blocks.extend([x for x in self.history_blocks if x])
        blocks.extend([x for x in self.context_blocks if x])
        return "\n\n".join(blocks)

    def model_input_en_or_fallback(self) -> str:
        if self.model_input_en:
            return self.model_input_en
        if self.user_question_en:
            return self.user_question_en
        return self.user_query

    # ------------------------------
    # Inbox helpers
    # ------------------------------

    def enqueue_message(
        self,
        *,
        target_step_id: str,
        topic: str,
        payload: Optional[Dict[str, Any]] = None,
        sender_step_id: Optional[str] = None,
    ) -> None:
        target = str(target_step_id or "").strip()
        t = str(topic or "").strip()
        if not target:
            raise ValueError("enqueue_message: target_step_id is required")
        if not t:
            raise ValueError("enqueue_message: topic is required")

        msg: Dict[str, Any] = {"target_step_id": target, "topic": t}
        if payload is not None:
            if not isinstance(payload, dict):
                raise ValueError("enqueue_message: payload must be a dict (JSON-serializable)")
            # Validate JSON-serializability deterministically (sorted keys, compact).
            try:
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            except Exception as ex:
                raise ValueError(f"enqueue_message: payload is not JSON-serializable: {ex}") from ex
            msg["payload"] = payload

        self.inbox.append(msg)

        # Record for log_out augmentation (base_action clears this per-step).
        try:
            buf = getattr(self, "_inbox_enqueued_buffer", None)
            if isinstance(buf, list):
                buf.append(msg)
        except Exception:
            pass

        # Always record an ENQUEUE trace event (if trace collection is enabled, engine will persist it).
        self._append_pipeline_trace_event(
            {
                "event_type": "ENQUEUE",
                "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "t_ms": int(time.time() * 1000),
                "run_id": getattr(self, "pipeline_run_id", None),
                "session_id": getattr(self, "session_id", None),
                "pipeline_name": getattr(self, "pipeline_name", None),
                "sender_step_id": sender_step_id or getattr(self, "_current_step_id", None),
                "target_step_id": target,
                "topic": t,
                "payload_summary": _payload_summary(payload),
            }
        )

    def consume_inbox_for_step(self, *, step_id: str) -> List[Dict[str, Any]]:
        sid = str(step_id or "").strip()
        if not sid:
            return []
        inbox = list(self.inbox or [])
        keep: List[Dict[str, Any]] = []
        taken: List[Dict[str, Any]] = []
        for msg in inbox:
            try:
                if str((msg or {}).get("target_step_id") or "").strip() == sid:
                    taken.append(msg)
                else:
                    keep.append(msg)
            except Exception:
                keep.append(msg)
        self.inbox = keep
        return taken

    def _append_pipeline_trace_event(self, event: Dict[str, Any]) -> None:
        lst = getattr(self, "pipeline_trace_events", None)
        if lst is None:
            lst = []
            setattr(self, "pipeline_trace_events", lst)
        lst.append(event)


def _payload_summary(payload: Optional[Dict[str, Any]], *, max_len: int = 400) -> str:
    if payload is None:
        return ""
    try:
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        s = repr(payload)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s
