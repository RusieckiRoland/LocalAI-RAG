# code_query_engine/pipeline/actions/call_model.py
from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase

from prompt_builder.factory import PromptRendererFactory


def _call_model_ask_with_compat(model: Any, *, prompt: str, context: str, question: str, consultant: str) -> str:
    """
    Compatibility shim:
      - if model.ask(prompt=..., consultant=...) exists -> use it
      - else if model.ask(context=..., question=..., consultant=...) exists -> use it
      - else fall back to positional best-effort
    """
    ask = getattr(model, "ask", None)
    if ask is None:
        raise AttributeError("Model has no .ask(...) method")

    try:
        sig = inspect.signature(ask)
        params = sig.parameters

        if "prompt" in params:
            return str(ask(prompt=prompt, consultant=consultant))

        if "context" in params and "question" in params:
            return str(ask(context=context, question=question, consultant=consultant))

    except Exception:
        # If signature introspection fails, fall back below.
        pass

    # Positional fallback
    try:
        return str(ask(prompt, consultant))
    except Exception:
        return str(ask(context, question, consultant))


class CallModelAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "call_model"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {
            "action": self.action_id,
            "step_id": getattr(step, "id", None),
            "prompt_key": (step.raw.get("prompt_key") if getattr(step, "raw", None) else None),
            "consultant": getattr(state, "consultant", None),
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
        out = getattr(state, "last_model_response", "") or ""
        return {
            "action": self.action_id,
            "step_id": getattr(step, "id", None),
            "next_step_id": next_step_id,
            "error": error,
            "last_model_response_preview": out[:200],
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        prompt_key = str((step.raw.get("prompt_key") or "")).strip()
        if not prompt_key:
            raise ValueError("call_model: missing required 'prompt_key' in step")

        # What the rest of the pipeline prepares
        context = str(getattr(state, "composed_context_for_prompt", "") or "")
        history = str(getattr(state, "history_for_prompt", "") or "")
        question = str(getattr(state, "model_input_en_or_fallback", "") or "")

        # Keep existing field (tests/debugging may rely on it)
        state.consultant = prompt_key

        model_path = str(getattr(runtime, "model_path", "") or "")
        prompts_dir = str(runtime.pipeline_settings.get("prompts_dir", "prompts"))

        renderer = PromptRendererFactory.create(
            model_path=model_path,
            prompts_dir=prompts_dir,
            system_prompt=str(runtime.pipeline_settings.get("system_prompt", "") or ""),
        )

        prompt = renderer.render(
            profile=prompt_key,
            context=context,
            question=question,
            history=history,
        )

        # Keep old debug field name
        state.next_codellama_prompt = prompt

        response = _call_model_ask_with_compat(
            runtime.main_model,
            prompt=prompt,
            context=context,
            question=question,
            consultant=prompt_key,
        )
        state.last_model_response = response

        # Keep old behavior: return explicit next if present (engine would also handle step.next)
        return getattr(step, "next", None) or (step.raw.get("next") if getattr(step, "raw", None) else None)
