# code_query_engine/pipeline/actions/call_model.py
from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional

from code_query_engine.chat_types import Dialog

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from ..cancellation import make_cancel_check
from .base_action import PipelineActionBase

from prompt_builder.factory import get_prompt_builder_by_prompt_format
from ..utils.step_overrides import get_override, opt_bool, opt_float, opt_int
import inspect

_TRACE_PROMPT_NAME_ATTR = "_pipeline_trace_prompt_name"
_TRACE_RENDERED_PROMPT_ATTR = "_pipeline_trace_rendered_prompt"
_TRACE_RENDERED_CHAT_MESSAGES_ATTR = "_pipeline_trace_rendered_chat_messages"
_TRACE_HISTORY_TRIM_ATTR = "_pipeline_trace_history_trim"


class CallModelAction(PipelineActionBase):
    """
    Call the main model using manual prompt builder (default) OR native chat mode.

    Notes:
    - We store rendered prompt into a private trace attribute for scenario debugging.
    - We intentionally keep logs bounded by truncating rendered prompt in log_out.
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
        raw = getattr(step, "raw", {}) or {}
        native_chat = opt_bool(get_override(raw=raw, settings=runtime.pipeline_settings, key="native_chat")) or False
        out = {
            "next_step_id": next_step_id,
            "error": error,
        }

        # Log ONLY the relevant rendered input for the current mode.
        # Otherwise, a previous call_model step may leave stale trace fields in state.
        if not native_chat:
            rendered = getattr(state, _TRACE_RENDERED_PROMPT_ATTR, None)
            if isinstance(rendered, str) and rendered:
                # DEV requirement: log full prompt (unbounded)
                out["rendered_prompt"] = rendered

        if native_chat:
            rendered_msgs = getattr(state, _TRACE_RENDERED_CHAT_MESSAGES_ATTR, None)
            if isinstance(rendered_msgs, list) and rendered_msgs:
                # DEV requirement: log full chat payload (unbounded)
                out["rendered_chat_messages"] = json.dumps(rendered_msgs, ensure_ascii=False)

        out["prompt_key"] = raw.get("prompt_key", "")
        out["native_chat"] = native_chat
        out["prompt_format"] = str(raw.get("prompt_format", "") or "")

        hist_trim = getattr(state, _TRACE_HISTORY_TRIM_ATTR, None)
        if isinstance(hist_trim, dict) and hist_trim:
            out["history_trim"] = hist_trim
        
        model_resp = getattr(state, "last_model_response", None)
        if isinstance(model_resp, str) and model_resp:
            out["model_response"] = model_resp[:9999]
            out["model_response_len"] = len(model_resp)
        return out

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # Logging-only: ensure per-step trace fields don't leak across multiple call_model steps
        # in a single pipeline run (router/summarizer/answer/etc.).
        try:
            setattr(state, _TRACE_RENDERED_PROMPT_ATTR, None)
            setattr(state, _TRACE_RENDERED_CHAT_MESSAGES_ATTR, None)
            setattr(state, _TRACE_HISTORY_TRIM_ATTR, None)
        except Exception:
            pass

        raw = getattr(step, "raw", {}) or {}
        prompt_key = str(raw.get("prompt_key") or "").strip()
        if not prompt_key:
            raise ValueError("call_model: prompt_key is required")

        native_chat = opt_bool(get_override(raw=raw, settings=runtime.pipeline_settings, key="native_chat")) or False

        prompt_format = str(raw.get("prompt_format") or "").strip()
        if not prompt_format:
            prompt_format = "codellama_inst_7_34"

        prompts_dir = str(getattr(runtime, "pipeline_settings", {}).get("prompts_dir", "prompts") or "prompts")

        system_prompt = self._load_system_prompt(
            prompts_dir=prompts_dir,
            prompt_key=prompt_key,
        )

        system_prompt, user_part, history = self._prepare_call_model_parts(
            step=step,
            state=state,
            runtime=runtime,
        )

        model = getattr(runtime, "model", None)
        if model is None:
            raise ValueError("call_model: runtime.model is required")

        model_kwargs: Dict[str, Any] = {}

        max_tokens = opt_int(get_override(raw=step.raw, settings=runtime.pipeline_settings, key="max_tokens"))
        # New alias: explicitly express output length limit (maps to model's max_tokens).
        max_output_tokens = opt_int(get_override(raw=step.raw, settings=runtime.pipeline_settings, key="max_output_tokens"))
        temperature = opt_float(get_override(raw=step.raw, settings=runtime.pipeline_settings, key="temperature"))
        top_k = opt_int(get_override(raw=step.raw, settings=runtime.pipeline_settings, key="top_k"))
        top_p = opt_float(get_override(raw=step.raw, settings=runtime.pipeline_settings, key="top_p"))
        server_name = str(get_override(raw=step.raw, settings=runtime.pipeline_settings, key="server_name") or "").strip()

        # Precedence: max_output_tokens overrides max_tokens if both are provided.
        if max_output_tokens is not None:
            model_kwargs["max_tokens"] = max_output_tokens
        elif max_tokens is not None:
            model_kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            model_kwargs["temperature"] = temperature
        if top_k is not None:
            model_kwargs["top_k"] = top_k
        if top_p is not None:
            model_kwargs["top_p"] = top_p
        if server_name and bool(getattr(model, "supports_server_name", False)):
            model_kwargs["server_name"] = server_name

        setattr(state, _TRACE_PROMPT_NAME_ATTR, prompt_key)

        if native_chat:
            out = self.ask_chat_mode_llm(
                state=state,
                model=model,
                system_prompt=system_prompt,
                user_part=user_part,
                history=history,
                model_kwargs=model_kwargs,
            )
        else:
            rendered_prompt = self._build_manual_prompt_and_trace(
                state=state,
                prompt_format=prompt_format,
                system_prompt=system_prompt,
                user_part=user_part,
                history=history,
            )

            out = self.ask_manual_prompt_llm(
                state=state,
                model=model,
                rendered_prompt=rendered_prompt,
                model_kwargs=model_kwargs,
            )

        state.last_model_response = str(out or "")
        return raw.get("next")

    def _load_system_prompt(self, *, prompts_dir: str, prompt_key: str) -> str:
        rel = f"{prompt_key}.txt"
        path = os.path.join(prompts_dir, rel)
        if not os.path.isfile(path):
            raise ValueError(f"call_model: system prompt file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


    def _eval_text(self, v: Any) -> str:
        if v is None:
            return ""
        if callable(v):
            v = v()

        if isinstance(v, list):
            out_parts: list[str] = []
            for item in v:
                if isinstance(item, dict) and "text" in item:
                    out_parts.append(str(item.get("text") or ""))
                else:
                    out_parts.append(str(item or ""))
            return "\n\n".join([p for p in out_parts if (p or "").strip()])

        return str(v or "")

    def _build_manual_prompt_and_trace(
        self,
        *,
        state: PipelineState,
        prompt_format: str,
        system_prompt: str,
        user_part: str,
        history: list[Any],
    ) -> str:
        rendered_prompt = self._build_manual_prompt(
            prompt_format=prompt_format,
            system_prompt=system_prompt,
            user_part=user_part,
            history=history,
        )
        setattr(state, _TRACE_RENDERED_PROMPT_ATTR, rendered_prompt)
        return rendered_prompt

    def _build_manual_prompt(
        self,
        *,
        prompt_format: str,
        system_prompt: str,
        user_part: str,
        history: list[Any],
    ) -> str:
        """
        Builds the final manual prompt string (e.g. CodeLlama [INST] format).

        Builder selection is delegated to the prompt_builder factory.
        Unknown prompt_format must fail-fast in the factory (English error message).
        """

        # Strict validation: history must be list[tuple[str,str]] (or empty).
        hist_pairs: Optional[list[tuple[str, str]]] = None
        if history:
            if not isinstance(history, list):
                raise ValueError("call_model: history must be a list")
            for i, item in enumerate(history):
                if not (isinstance(item, tuple) and len(item) == 2 and all(isinstance(x, str) for x in item)):
                    raise ValueError(f"call_model: history[{i}] must be tuple[str,str]")
            hist_pairs = history  # type: ignore[assignment]

        builder = get_prompt_builder_by_prompt_format(prompt_format)
        return builder.build_prompt(
            modelFormatedText=user_part,
            history=hist_pairs,
            system_prompt=system_prompt,
        )

    def ask_chat_mode_llm(
    self,
    *,
    state: PipelineState,
    model: Any,
    system_prompt: str,
    user_part: str,
    history: Dialog,
    model_kwargs: Dict[str, Any],
    ) -> str:
        ask_chat = getattr(model, "ask_chat", None)
        if not callable(ask_chat):
            raise ValueError(
                "call_model: native_chat=true requires model.ask_chat(...). "
                "Disable via step.native_chat: false or pipeline settings.native_chat: false."
            )

        # history is Dialog (list of {"role": "...", "content": "..."}) or empty.
        hist_dialog: Optional[Dialog] = None
        if history:
            if not isinstance(history, list):
                raise ValueError("call_model: history must be a list (Dialog)")
            hist_dialog = history

        # Build exact chat payload for tracing (equivalent to rendered_prompt in manual mode).
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        if hist_dialog:
            for i, msg in enumerate(hist_dialog):
                if not isinstance(msg, dict):
                    raise ValueError(f"call_model: history[{i}] must be a dict (Dialog message)")

                role = str(msg.get("role") or "").strip()
                content = str(msg.get("content") or "").strip()

                if not role or not content:
                    continue

                # system_prompt is passed separately; do not duplicate it from history
                if role == "system":
                    continue

                if role not in ("user", "assistant"):
                    raise ValueError(
                        f"call_model: history[{i}].role must be 'user' or 'assistant' (or 'system'), got: {role!r}"
                    )

                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_part})
        setattr(state, _TRACE_RENDERED_CHAT_MESSAGES_ATTR, messages)

        cancel_check = make_cancel_check(state) if bool(getattr(model, "supports_cancel_check", False)) else None
        call_kwargs = dict(model_kwargs)
        if cancel_check is not None:
            call_kwargs["cancel_check"] = cancel_check
        return str(
            ask_chat(
                prompt=user_part,
                history=hist_dialog,
                system_prompt=system_prompt,
                **call_kwargs,
            )
            or ""
        )


    def ask_manual_prompt_llm(
        self,
        *,
        state: Optional[PipelineState] = None,
        model: Any,
        rendered_prompt: str,
        model_kwargs: Dict[str, Any],
    ) -> str:
        ask = getattr(model, "ask", None)
        if not callable(ask):
            raise ValueError("call_model: model.ask(...) is required")

        cancel_check = None
        if state is not None and bool(getattr(model, "supports_cancel_check", False)):
            cancel_check = make_cancel_check(state)
        call_kwargs = dict(model_kwargs)
        if cancel_check is not None:
            call_kwargs["cancel_check"] = cancel_check
        return str(
            ask(
                prompt=rendered_prompt,
                system_prompt=None,
                **call_kwargs,
            )
            or ""
        )
    def _prepare_call_model_parts(
        self,
        *,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
    ) -> tuple[str, str, Dialog]:
        raw = getattr(step, "raw", {}) or {}

        prompts_dir = str(getattr(runtime, "pipeline_settings", {}).get("prompts_dir", "prompts") or "prompts")
        prompt_key = str(raw.get("prompt_key") or "").strip()
        system_prompt = self._load_system_prompt(prompts_dir=prompts_dir, prompt_key=prompt_key)

        # New YAML shape:
        # user_parts:
        #   evidence:
        #     source: context_blocks
        #     template: "### Evidence:\n{}\n\n"
        #   user_question:
        #     source: user_question_neutral
        #     template: "### User:\n{}\n\n"
        user_parts_cfg = raw.get("user_parts")
        native_chat = opt_bool(get_override(raw=raw, settings=runtime.pipeline_settings, key="native_chat")) or False
        if not isinstance(user_parts_cfg, dict) or not user_parts_cfg:
            if native_chat:
                # Native chat: allow empty user_parts and fallback to user_question_neutral or user_query.
                user_part_fallback = str(getattr(state, "user_question_neutral", None) or getattr(state, "user_query", "") or "")
                user_part = user_part_fallback.strip()
                history: Dialog = list(getattr(state, "history_dialog", None) or []) if bool(raw.get("use_history", False)) else []
                return system_prompt, user_part, history
            raise ValueError("call_model: user_parts must be a non-empty dict")

        # History source is fixed: state.history_dialog (Dialog).
        use_history = bool(raw.get("use_history", False))
        history: Dialog = list(getattr(state, "history_dialog", None) or []) if use_history else []
        if use_history:
            max_history_tokens = (getattr(runtime, "pipeline_settings", {}) or {}).get("max_history_tokens")
            if max_history_tokens is not None:
                try:
                    max_history_tokens_i = int(max_history_tokens)
                except Exception as ex:
                    raise ValueError("call_model: settings.max_history_tokens must be int") from ex
                if max_history_tokens_i < 0:
                    raise ValueError("call_model: settings.max_history_tokens must be >= 0")
                if max_history_tokens_i == 0:
                    history = []
                    setattr(state, _TRACE_HISTORY_TRIM_ATTR, {"policy": "max_history_tokens", "before": len(getattr(state, "history_dialog", []) or []), "after": 0})
                else:
                    history_before = len(history)
                    history = self._trim_history_dialog_by_token_budget(
                        history=history,
                        token_budget=max_history_tokens_i,
                        token_counter=getattr(runtime, "token_counter", None),
                    )
                    if len(history) != history_before:
                        setattr(
                            state,
                            _TRACE_HISTORY_TRIM_ATTR,
                            {"policy": "max_history_tokens", "before": history_before, "after": len(history)},
                        )

        user_parts_out: list[str] = []

        # Order matters: YAML insertion order defines concatenation order.
        for part_name, spec in user_parts_cfg.items():
            if not isinstance(part_name, str) or not part_name.strip():
                raise ValueError("call_model: user_parts keys must be non-empty strings")

            if not isinstance(spec, dict):
                raise ValueError(f"call_model: user_parts['{part_name}'] must be a dict")

            source = str(spec.get("source") or "").strip()
            template = spec.get("template")

            if not source:
                raise ValueError(f"call_model: user_parts['{part_name}'].source must be a non-empty string")
            if not isinstance(template, str) or "{}" not in template:
                raise ValueError(
                    f"call_model: user_parts['{part_name}'].template must be a format string containing '{{}}'"
                )

            v = getattr(state, source, None)
            if callable(v):
                v = v()

            text = self._eval_text(v).strip()
            user_parts_out.append(template.format(text))

        user_part = "".join(user_parts_out)
        return system_prompt, user_part, history

    def _trim_history_dialog_by_token_budget(self, *, history: Dialog, token_budget: int, token_counter: Any) -> Dialog:
        """
        Best-effort: trims oldest turns first to stay within token_budget.
        This uses the runtime token counter if available; otherwise it returns history unchanged.
        """
        if token_budget <= 0:
            return []
        if token_counter is None or not callable(getattr(token_counter, "token_count", None)):
            return history

        def _turn_tokens(turn: tuple[str, str]) -> int:
            u, a = turn
            # Conservative overhead for role wrappers / separators in prompt builder.
            overhead = 32
            return int(token_counter.token_count((u or "") + "\n\n" + (a or ""))) + overhead

        # Keep most recent turns; drop from the front until fits.
        turns = list(history or [])
        total = sum(_turn_tokens(t) for t in turns)
        if total <= token_budget:
            return turns

        while turns and total > token_budget:
            total -= _turn_tokens(turns[0])
            turns.pop(0)

        return turns
