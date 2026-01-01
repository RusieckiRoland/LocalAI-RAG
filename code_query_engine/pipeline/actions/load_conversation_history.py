# code_query_engine/pipeline/actions/load_conversation_history.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from   typing import Any, Dict
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
        return {
            "next_step_id": next_step_id,
            "history_blocks_count": len(getattr(state, "history_blocks", []) or []),
            "history_blocks": getattr(state, "history_blocks", []),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        try:
            state.history_blocks = runtime.history_manager.get_context_blocks() or []
        except Exception:
            # History must never break the main flow
            state.history_blocks = []
        return None
