# code_query_engine/pipeline/actions/load_conversation_history.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class LoadConversationHistoryAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        try:
            state.history_blocks = runtime.history_manager.get_context_blocks() or []
        except Exception:
            # History must never break the main flow
            state.history_blocks = []
        return None
