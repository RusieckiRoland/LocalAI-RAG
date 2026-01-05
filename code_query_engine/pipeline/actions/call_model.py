# code_query_engine/pipeline/actions/call_model.py
from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase
from pathlib import Path

from prompt_builder.factory import PromptRendererFactory

_TRACE_PROMPT_NAME_ATTR = "_pipeline_trace_prompt_name"
_TRACE_RENDERED_PROMPT_ATTR = "_pipeline_trace_rendered_prompt"


def _call_model_ask_with_compat(model: Any, *, prompt: str, context: str, question: str, consultant: str) -> str:
    ask = getattr(model, "ask", None)
    if ask is None:
        raise AttributeError("Model has no .ask(...) method")

    try:
        return str(ask(prompt=prompt, consultant=consultant))
    except TypeError:
        pass

    try:
        return str(ask(context=context, question=question, consultant=consultant))
    except TypeError:
        pass

    raise TypeError(
        "Model.ask() must support keyword-only signature: "
        "ask(prompt=..., consultant=...) or ask(context=..., question=..., consultant=...)"
    )


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

        prompt_name = getattr(runtime, _TRACE_PROMPT_NAME_ATTR, None)
        rendered_prompt = getattr(runtime, _TRACE_RENDERED_PROMPT_ATTR, None)

        # Cleanup: never leak between steps/runs
        if hasattr(runtime, _TRACE_PROMPT_NAME_ATTR):
            try:
                delattr(runtime, _TRACE_PROMPT_NAME_ATTR)
            except Exception:
                pass

        if hasattr(runtime, _TRACE_RENDERED_PROMPT_ATTR):
            try:
                delattr(runtime, _TRACE_RENDERED_PROMPT_ATTR)
            except Exception:
                pass

        return {
            "action": self.action_id,
            "step_id": getattr(step, "id", None),
            "next_step_id": next_step_id,
            "error": error,

            # requested step-level logging
            "prompt_template_raw": prompt_name,
            "rendered_prompt": rendered_prompt,

            "last_model_response_preview": out[:200],
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        prompt_key = str((step.raw.get("prompt_key") or "")).strip()
        if not prompt_key:
            raise ValueError("call_model: missing required 'prompt_key' in step")

        # What the rest of the pipeline prepares
        def _to_text(v: object) -> str:
            if callable(v):
                v = v()
            return str(v or "")

        context = _to_text(getattr(state, "composed_context_for_prompt", ""))
        question = _to_text(getattr(state, "model_input_en_or_fallback", getattr(state, "user_query", "")))
        history = _to_text(getattr(state, "history_for_prompt", ""))



        # consultant is the pipeline identity; never overwrite it with prompt_key
        consultant = str(getattr(state, "consultant", "") or "")

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

        # Store prompt only for step logging (per-request runtime), NOT in state
        setattr(runtime, _TRACE_PROMPT_NAME_ATTR, prompt_key)
        setattr(runtime, _TRACE_RENDERED_PROMPT_ATTR, prompt)

        response = _call_model_ask_with_compat(
            runtime.main_model,
            prompt=prompt,
            context=context,
            question=question,
            consultant=consultant,
        )
        state.last_model_response = response

        # Keep old behavior: return explicit next if present (engine would also handle step.next)
        return getattr(step, "next", None) or (step.raw.get("next") if getattr(step, "raw", None) else None)
