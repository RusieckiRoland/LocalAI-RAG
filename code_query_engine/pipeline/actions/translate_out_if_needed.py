# code_query_engine/pipeline/actions/translate_out_if_needed.py

from __future__ import annotations

from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


class TranslateOutIfNeededAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "translate_out_if_needed"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        tr = getattr(runtime, "markdown_translator", None)
        return {
            "translate_chat": bool(getattr(state, "translate_chat", False)),
            "translator_present": bool(tr is not None and hasattr(tr, "translate")),
            "answer_en_present": bool((getattr(state, "answer_en", None) or "").strip()),
        }

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
            "answer_translated_present": bool((getattr(state, "answer_translated", None) or "").strip()),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
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
                    state.answer_translated = fn(answer_en)
                    return None
                except Exception:
                    pass

        # Fallback: keep EN if no translator is available.
        state.answer_translated = answer_en
        return None
