# code_query_engine/pipeline/actions/load_conversation_history.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from typing import Any, Dict
from .base_action import PipelineActionBase


class LoadConversationHistoryAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "load_conversation_history"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {"session_id": state.session_id}

    def log_out(
        self,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
        *,
        next_step_id: Optional[str],
        error: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        out = {
            "next_step_id": next_step_id,
            "history_blocks_count": len(getattr(state, "history_blocks", []) or []),
        }
        if self._full_trace_allowed(runtime):
            out["history_blocks"] = getattr(state, "history_blocks", [])
        return out

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        limit = raw.get("history_limit")
        try:
            limit_i = int(limit) if limit is not None else 30
        except Exception:
            limit_i = 30
        if limit_i <= 0:
            limit_i = 30

        svc = getattr(runtime, "conversation_history_service", None)
        get_recent = getattr(svc, "get_recent_qa_neutral", None) if svc is not None else None
        if callable(get_recent):
            try:
                qa = get_recent(session_id=state.session_id, limit=limit_i) or []
                if not isinstance(qa, list):
                    qa = []

                state.history_qa_neutral = qa

                # Dialog form is used by call_model native_chat mode (state.history_dialog).
                dialog: list[dict[str, str]] = []
                blocks: list[str] = []
                for q, a in qa:
                    q_s = str(q or "").strip()
                    a_s = str(a or "").strip()
                    if not q_s or not a_s:
                        continue
                    dialog.append({"role": "user", "content": q_s})
                    dialog.append({"role": "assistant", "content": a_s})
                    blocks.append(f"User asked: {q_s}")
                    blocks.append(f"Final answer: {a_s}")

                state.history_dialog = dialog
                state.history_blocks = blocks
                return None
            except Exception:
                # History must never break the main flow
                state.history_qa_neutral = []
                state.history_dialog = []
                state.history_blocks = []
                return None

        try:
            state.history_blocks = runtime.history_manager.get_context_blocks() or []
        except Exception:
            # History must never break the main flow
            state.history_blocks = []
        return None
