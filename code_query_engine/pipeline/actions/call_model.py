# code_query_engine/pipeline/actions/call_model.py
from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase

from prompt_builder.factory import PromptRendererFactory

_TRACE_PROMPT_NAME_ATTR = "_pipeline_trace_prompt_name"
_TRACE_RENDERED_PROMPT_ATTR = "_pipeline_trace_rendered_prompt"


def _call_model_ask_with_compat(
    model: Any,
    *,
    prompt: str,
    context: str,
    question: str,
    consultant: str,
    system_prompt: str,
    model_kwargs: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Prefer model.ask(...) to support your Model wrapper (keyword-only signature).
    Compat modes:
    - ask(prompt=..., consultant=..., system_prompt=...)
    - ask(context=..., question=..., consultant=..., system_prompt=...)
    """
    ask = getattr(model, "ask", None)
    if not callable(ask):
        raise ValueError("call_model: main_model must have callable .ask(...)")

    sig = None
    try:
        sig = inspect.signature(ask)
        params = dict(sig.parameters)
    except Exception:
        params = None

    # Optional generation overrides (e.g., max_tokens, temperature, top_k, top_p).
    extra: Dict[str, Any] = dict(model_kwargs or {})
    if params is not None:
        # Only pass supported kwargs unless the model explicitly accepts **kwargs.
        accepts_var_kw = False
        if sig is not None:
            for p in sig.parameters.values():
                if p.kind == inspect.Parameter.VAR_KEYWORD:
                    accepts_var_kw = True
                    break
        if not accepts_var_kw:
            extra = {k: v for k, v in extra.items() if k in params}

    def _try_prompt_kw() -> str:
        bases = (
            {"prompt": prompt, "consultant": consultant, "system_prompt": system_prompt},
            {"prompt": prompt, "consultant": consultant},
            {"prompt": prompt},
        )

        for base in bases:
            candidates = []
            if extra:
                candidates.append({**base, **extra})
            candidates.append(base)

            for kw in candidates:
                try:
                    return str(ask(**kw))
                except TypeError:
                    continue

        raise TypeError("ask(prompt=...) not supported")

    def _try_ctxq_kw() -> str:
        bases = (
            {"context": context, "question": question, "consultant": consultant, "system_prompt": system_prompt},
            {"context": context, "question": question, "consultant": consultant},
            {"context": context, "question": question},
        )

        for base in bases:
            candidates = []
            if extra:
                candidates.append({**base, **extra})
            candidates.append(base)

            for kw in candidates:
                try:
                    return str(ask(**kw))
                except TypeError:
                    continue

        raise TypeError("ask(context=..., question=...) not supported")

    if params is not None:
        if "prompt" in params:
            return _try_prompt_kw()
        if "context" in params and "question" in params:
            return _try_ctxq_kw()

    try:
        return _try_prompt_kw()
    except TypeError:
        return _try_ctxq_kw()


class CallModelAction(PipelineActionBase):
    """
    Call the main model using PromptRenderer and store its final output in state.last_model_response.

    Notes:
    - We store rendered prompt into a private trace attribute for scenario debugging.
    - We intentionally keep logs bounded by truncating rendered prompt in log_out (full prompt still available in traces).
    """

    action_id = "call_model"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = getattr(step, "raw", {}) or {}
        return {
            "prompt_key": raw.get("prompt_key", ""),
            "model_path": str(getattr(runtime, "model_path", "") or ""),
            "prompts_dir": str(getattr(runtime, "pipeline_settings", {}).get("prompts_dir", "") or ""),
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
        rendered = str(getattr(state, _TRACE_RENDERED_PROMPT_ATTR, "") or "")
        preview = rendered[:600] + ("..." if len(rendered) > 600 else "")
        return {
            "next_step_id": next_step_id,
            "error": error,
            "prompt_key": str(getattr(state, _TRACE_PROMPT_NAME_ATTR, "") or ""),
            "rendered_prompt": preview,
            "last_model_response_len": len(str(getattr(state, "last_model_response", "") or "")),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> None:
        raw = getattr(step, "raw", {}) or {}
        prompt_key = str(raw.get("prompt_key") or "").strip()
        if not prompt_key:
            raise ValueError("call_model: missing 'prompt_key' on step")

        # Resolve system prompt: prefer pipeline_settings["system_prompt"].
        system_prompt = str(getattr(runtime, "pipeline_settings", {}).get("system_prompt", "") or "")

        # Create renderer (renderer will load prompt_key file into SYS block)
        model_path = str(getattr(runtime, "model_path", "") or "")
        prompts_dir = str(getattr(runtime, "pipeline_settings", {}).get("prompts_dir", "prompts") or "prompts")
        renderer = PromptRendererFactory.create(model_path=model_path, prompts_dir=prompts_dir, system_prompt=system_prompt)

        def _to_text(v: object) -> str:
            # IMPORTANT: some state "fields" are methods; we must call them.
            if callable(v):
                v = v()
            return str(v or "")

        def _join_list(items: object) -> str:
            # Normalize a source into a single text blob.
            if items is None:
                return ""
            if callable(items):
                items = items()
            if items is None:
                return ""
            if isinstance(items, list):
                parts = []
                for x in items:
                    if x is None:
                        continue
                    if isinstance(x, dict) and "text" in x:
                        t = str(x.get("text") or "")
                    else:
                        t = _to_text(x)
                    t = str(t or "").strip()
                    if not t:
                        continue
                    parts.append(t)
                return "\n\n".join(parts)
            return _to_text(items).strip()

        raw_inputs = raw.get("inputs") if isinstance(raw, dict) else None
        raw_inputs = raw_inputs if isinstance(raw_inputs, dict) else {}

        prefixes = raw.get("prefixes") if isinstance(raw, dict) else None
        prefixes = prefixes if isinstance(prefixes, dict) else {}

        def _ensure_fmt(s: str, *, key: str) -> str:
            txt = str(s or "")
            if "{}" not in txt:
                raise ValueError(f"call_model: prefix '{key}' must contain '{{}}' placeholder")
            return txt

        def _maybe_wrap(prefix_key: str, text: str, default_fmt: str) -> str:
            if not text.strip():
                return ""
            fmt = prefixes.get(prefix_key)
            if fmt is None:
                fmt = default_fmt
            fmt = _ensure_fmt(str(fmt), key=prefix_key)
            return fmt.format(text)

        if raw_inputs:
            h_src = str(raw_inputs.get("history_from") or "").strip()
            e_src = str(raw_inputs.get("evidence_from") or "").strip()
            q_src = str(raw_inputs.get("user_from") or "").strip()

            history_text = _join_list(getattr(state, h_src, "")) if h_src else _join_list(getattr(state, "history_blocks", ""))
            evidence_text = _join_list(getattr(state, e_src, "")) if e_src else _join_list(getattr(state, "context_blocks", ""))

            if q_src:
                q_val = getattr(state, q_src, "")
            else:
                q_val = getattr(state, "model_input_en_or_fallback", getattr(state, "user_query", ""))
            question_text = _to_text(q_val).strip()

            # IMPORTANT: lower prompt is 100% YAML-driven (prefixes + inputs)
            context = (
                _maybe_wrap("history_prefix", history_text, "### History:\n{}\n\n")
                + _maybe_wrap("evidence_prefix", evidence_text, "### Evidence:\n{}\n\n")
            )
            question = _maybe_wrap("question_prefix", question_text, "### User:\n{}\n\n")
            history = ""
        else:
            # Legacy/default behavior (no inputs): keep existing state methods/fields.
            context = _to_text(getattr(state, "composed_context_for_prompt", ""))
            question = _to_text(getattr(state, "model_input_en_or_fallback", getattr(state, "user_query", "")))
            history = _to_text(getattr(state, "history_for_prompt", ""))

        rendered_prompt = renderer.render(profile=prompt_key, context=context, question=question, history=history)

        setattr(state, _TRACE_PROMPT_NAME_ATTR, prompt_key)
        setattr(state, _TRACE_RENDERED_PROMPT_ATTR, rendered_prompt)

        model = getattr(runtime, "main_model", None)
        if model is None:
            raise ValueError("call_model: runtime.main_model is not set")

        consultant = str(getattr(state, "consultant", "") or "")
        system_prompt = str(getattr(runtime, "pipeline_settings", {}).get("system_prompt", "") or "")

        # Optional generation overrides (step-level keys override pipeline settings).
        settings = getattr(runtime, "pipeline_settings", {}) or {}

        def _opt_int(v: object) -> Optional[int]:
            if v is None:
                return None
            if isinstance(v, bool):
                return None
            if isinstance(v, int):
                return v
            s = str(v or "").strip()
            if not s:
                return None
            return int(s)

        def _opt_float(v: object) -> Optional[float]:
            if v is None:
                return None
            if isinstance(v, bool):
                return None
            if isinstance(v, float):
                return v
            if isinstance(v, int):
                return float(v)
            s = str(v or "").strip()
            if not s:
                return None
            return float(s)

        def _get_override(key: str) -> object:
            # Step-level value wins if present (even if None is explicitly set).
            if isinstance(raw, dict) and key in raw:
                return raw.get(key)
            return settings.get(key)

        model_kwargs: Dict[str, Any] = {}

        max_tokens = _opt_int(_get_override("max_tokens"))
        temperature = _opt_float(_get_override("temperature"))
        top_k = _opt_int(_get_override("top_k"))
        top_p = _opt_float(_get_override("top_p"))

        if max_tokens is not None:
            model_kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            model_kwargs["temperature"] = temperature
        if top_k is not None:
            model_kwargs["top_k"] = top_k
        if top_p is not None:
            model_kwargs["top_p"] = top_p

        ask = getattr(model, "ask", None)
        if callable(ask):
            out = _call_model_ask_with_compat(
                model,
                prompt=rendered_prompt,
                context=context,
                question=question,
                consultant=consultant,
                system_prompt=system_prompt,
                model_kwargs=model_kwargs,
            )
        else:
            gen = getattr(model, "generate", None)
            if callable(gen):
                out = gen(rendered_prompt, consultant, system_prompt)
            elif callable(model):
                out = model(rendered_prompt, consultant, system_prompt)
            else:
                raise ValueError("call_model: main_model must have .ask(...) or be callable or have .generate(...)")

        setattr(state, "last_model_response", out)
