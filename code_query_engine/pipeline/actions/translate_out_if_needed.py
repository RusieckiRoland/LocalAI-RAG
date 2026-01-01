# code_query_engine/pipeline/actions/translate_out_if_needed.py

from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from typing import Any, Dict
from .base_action import PipelineActionBase 

class TranslateOutIfNeededAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        if not getattr(state, "translate_chat", False):
            return None

        answer_en = (getattr(state, "answer_en", None) or "").strip()
        if not answer_en:
            return None

        # Prefer markdown-aware translation if available.
        translator = getattr(runtime, "markdown_translator", None)
        if translator is not None:
            fn = getattr(translator, "translate", None)
            if callable(fn):
                try:
                    state.answer_pl = fn(answer_en)
                    return None
                except Exception:
                    pass

        # Fallback: keep EN if no translator is available.
        state.answer_pl = answer_en
        return None
