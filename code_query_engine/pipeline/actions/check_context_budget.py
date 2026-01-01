# code_query_engine/pipeline/actions/check_context_budget.py
from __future__ import annotations

from typing import Optional, Any, Dict

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from .base_action import PipelineActionBase



def _approx_tokens(text: str) -> int:
    # Deterministic approximation (no external tokenizer).
    return len((text or "").split())


class CheckContextBudgetAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "check_context_budget"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        input_key = (step.raw.get("input") or "").strip() or "composed_context_for_prompt"
        max_key = (step.raw.get("max_tokens_from_settings") or "").strip() or "context_budget_tokens"
        settings: Dict[str, Any] = runtime.pipeline_settings or {}
        return {
            "input_key": input_key,
            "max_key": max_key,
            "max_tokens": settings.get(max_key),
            "token_counter_present": bool(runtime.token_counter),
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
            "budget_debug": getattr(state, "budget_debug", None),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        input_key = (step.raw.get("input") or "").strip()
        max_key = (step.raw.get("max_tokens_from_settings") or "").strip()

        # Backward-compatible defaults for older YAML steps
        if not input_key:
            input_key = "composed_context_for_prompt"
        if not max_key:
            max_key = "context_budget_tokens"


        settings: Dict[str, Any] = runtime.pipeline_settings or {}
        if max_key not in settings:
            raise ValueError(f"Missing settings key for budget: '{max_key}'")
        max_tokens = int(settings[max_key])

        if input_key == "history_for_prompt":
            text = state.history_for_prompt()
        elif input_key == "composed_context_for_prompt":
            text = state.composed_context_for_prompt()
        else:
            raise ValueError(f"Unknown budget input: '{input_key}'")

        token_counter = runtime.token_counter
        tokens = int(token_counter.count(text)) if token_counter else _approx_tokens(text)

        state.budget_debug = {
            "input": input_key,
            "tokens": tokens,
            "max_tokens": max_tokens,
        }

        if tokens > max_tokens:
            return step.raw.get("on_over_limit")
        return step.raw.get("on_ok")
