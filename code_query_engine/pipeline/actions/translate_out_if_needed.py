# code_query_engine/pipeline/actions/translate_out_if_needed.py

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Optional

from prompt_builder.factory import get_prompt_builder_by_prompt_format

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase
from ..utils.step_overrides import get_override, opt_bool, opt_float, opt_int

_TRACE_TRANSLATE_RENDERED_PROMPT_ATTR = "_pipeline_trace_translate_rendered_prompt"
_TRACE_TRANSLATE_RENDERED_CHAT_MESSAGES_ATTR = "_pipeline_trace_translate_rendered_chat_messages"
_TRACE_TRANSLATE_MODEL_RESPONSE_ATTR = "_pipeline_trace_translate_model_response"
_TRACE_TRANSLATE_INPUT_SUMMARY_ATTR = "_pipeline_trace_translate_input_summary"


class TranslateOutIfNeededAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "translate_out_if_needed"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = getattr(step, "raw", {}) or {}
        tr = getattr(runtime, "markdown_translator", None)
        has_translate_markdown = bool(tr is not None and callable(getattr(tr, "translate_markdown", None)))
        has_translate = bool(tr is not None and callable(getattr(tr, "translate", None)))
        answer_en = (getattr(state, "answer_en", None) or "").strip()
        return {
            "translate_chat": bool(getattr(state, "translate_chat", False)),
            "translator_present": bool(has_translate_markdown or has_translate),
            "translator_has_translate_markdown": has_translate_markdown,
            "translator_has_translate": has_translate,
            "answer_en_present": bool(answer_en),
            "answer_en_chars": len(answer_en),
            "use_main_model": bool(raw.get("use_main_model") is True),
            "translate_prompt_key": str(raw.get("translate_prompt_key") or ""),
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
        out: Dict[str, Any] = {
            "next_step_id": next_step_id,
            "answer_translated_present": bool((getattr(state, "answer_translated", None) or "").strip()),
        }
        summary = getattr(state, _TRACE_TRANSLATE_INPUT_SUMMARY_ATTR, None)
        if isinstance(summary, dict) and summary:
            out["translate_input_summary"] = summary
        rendered = getattr(state, _TRACE_TRANSLATE_RENDERED_PROMPT_ATTR, None)
        if isinstance(rendered, str) and rendered:
            out["rendered_prompt"] = rendered
        rendered_msgs = getattr(state, _TRACE_TRANSLATE_RENDERED_CHAT_MESSAGES_ATTR, None)
        if isinstance(rendered_msgs, list) and rendered_msgs:
            out["rendered_chat_messages"] = rendered_msgs
        resp = getattr(state, _TRACE_TRANSLATE_MODEL_RESPONSE_ATTR, None)
        if isinstance(resp, str) and resp:
            out["model_response"] = resp[:9999]
            out["model_response_len"] = len(resp)
        return out

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # Logging-only: avoid leaking trace fields across steps/runs.
        try:
            setattr(state, _TRACE_TRANSLATE_RENDERED_PROMPT_ATTR, None)
            setattr(state, _TRACE_TRANSLATE_RENDERED_CHAT_MESSAGES_ATTR, None)
            setattr(state, _TRACE_TRANSLATE_MODEL_RESPONSE_ATTR, None)
            setattr(state, _TRACE_TRANSLATE_INPUT_SUMMARY_ATTR, None)
        except Exception:
            pass

        if not getattr(state, "translate_chat", False):
            return None

        answer_en = (getattr(state, "answer_en", None) or "").strip()
        if not answer_en:
            return None

        raw = getattr(step, "raw", {}) or {}
        use_main_model = bool(raw.get("use_main_model") is True)
        translate_prompt_key = str(raw.get("translate_prompt_key") or "").strip()

        if use_main_model:
            if not translate_prompt_key:
                raise ValueError("translate_out_if_needed: translate_prompt_key is required when use_main_model is true")

            # Allow Windows-style separators in YAML (e.g. utilities\\translate_en_pl).
            translate_prompt_key_norm = translate_prompt_key.replace("\\", "/")

            prompts_dir = str(getattr(runtime, "pipeline_settings", {}).get("prompts_dir", "prompts") or "prompts")
            rel = f"{translate_prompt_key_norm}.txt"
            path = os.path.join(prompts_dir, rel)
            if not os.path.isfile(path):
                raise ValueError(f"translate_out_if_needed: system prompt file not found: {path}")
            with open(path, "r", encoding="utf-8") as f:
                system_prompt = f.read()

            model = getattr(runtime, "model", None)
            if model is None:
                raise ValueError("translate_out_if_needed: runtime.model is required when use_main_model is true")

            # If the translation prompt expects a delimited input block, comply.
            # Heuristic: detect common markers used in our prompt templates.
            user_payload = answer_en
            wrap_mode = ""
            if "<<<MARKDOWN_EN" in system_prompt and "MARKDOWN_EN" in system_prompt:
                user_payload = f"<<<MARKDOWN_EN\n{answer_en}\nMARKDOWN_EN"
                wrap_mode = "MARKDOWN_EN"
            elif "<<<TEXT" in system_prompt and "\nTEXT" in system_prompt:
                user_payload = f"<<<TEXT\n{answer_en}\nTEXT"
                wrap_mode = "TEXT"

            model_kwargs: Dict[str, Any] = {}
            max_tokens = opt_int(get_override(raw=raw, settings=runtime.pipeline_settings, key="max_tokens"))
            max_output_tokens = opt_int(get_override(raw=raw, settings=runtime.pipeline_settings, key="max_output_tokens"))
            temperature = opt_float(get_override(raw=raw, settings=runtime.pipeline_settings, key="temperature"))
            top_k = opt_int(get_override(raw=raw, settings=runtime.pipeline_settings, key="top_k"))
            top_p = opt_float(get_override(raw=raw, settings=runtime.pipeline_settings, key="top_p"))

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

            native_chat = opt_bool(get_override(raw=raw, settings=runtime.pipeline_settings, key="native_chat")) or False
            try:
                # Trace what goes into the model (compact + safe-ish).
                # Full payload is already recorded when tracing is enabled and native_chat is used,
                # but this summary helps quickly spot accidental context injection.
                try:
                    def _sha256(s: str) -> str:
                        return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

                    payload = user_payload or ""
                    summary = {
                        "native_chat": bool(native_chat),
                        "prompt_format": str(raw.get("prompt_format") or "").strip() or "codellama_inst_7_34",
                        "wrap_mode": wrap_mode,
                        "answer_en_chars": len(answer_en),
                        "user_payload_chars": len(payload),
                        "user_payload_lines": payload.count("\n") + (1 if payload else 0),
                        "sha256_system_prompt": _sha256(system_prompt),
                        "sha256_user_payload": _sha256(payload),
                        "contains_markers": {
                            "has_evidence_block": ("<<<EVIDENCE" in payload) or ("\nEVIDENCE" in payload),
                            "has_node_blocks": ("--- NODE ---" in payload),
                            "has_user_question_block": ("<<<USER_QUESTION" in payload) or ("\nUSER_QUESTION" in payload),
                        },
                        "counts": {
                            "triple_backticks": payload.count("```"),
                            "node_blocks": payload.count("--- NODE ---"),
                        },
                        "user_payload_preview": payload[:400],
                    }
                    setattr(state, _TRACE_TRANSLATE_INPUT_SUMMARY_ATTR, summary)
                except Exception:
                    pass

                if native_chat:
                    ask_chat = getattr(model, "ask_chat", None)
                    if not callable(ask_chat):
                        raise ValueError("translate_out_if_needed: model.ask_chat(...) is required for native_chat mode")
                    try:
                        setattr(
                            state,
                            _TRACE_TRANSLATE_RENDERED_CHAT_MESSAGES_ATTR,
                            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_payload}],
                        )
                    except Exception:
                        pass

                    resp = str(
                        ask_chat(
                            prompt=user_payload,
                            history=[],
                            system_prompt=system_prompt,
                            **model_kwargs,
                        )
                        or ""
                    ).strip()
                    try:
                        setattr(state, _TRACE_TRANSLATE_MODEL_RESPONSE_ATTR, resp)
                    except Exception:
                        pass
                    state.answer_translated = resp or answer_en
                    return None

                prompt_format = str(raw.get("prompt_format") or "").strip() or "codellama_inst_7_34"
                builder = get_prompt_builder_by_prompt_format(prompt_format)
                rendered = builder.build_prompt(
                    modelFormatedText=user_payload,
                    history=None,
                    system_prompt=system_prompt,
                )
                try:
                    setattr(state, _TRACE_TRANSLATE_RENDERED_PROMPT_ATTR, rendered)
                except Exception:
                    pass

                ask = getattr(model, "ask", None)
                if not callable(ask):
                    raise ValueError("translate_out_if_needed: model.ask(...) is required")
                resp = str(ask(prompt=rendered, system_prompt=None, **model_kwargs) or "").strip()
                try:
                    setattr(state, _TRACE_TRANSLATE_MODEL_RESPONSE_ATTR, resp)
                except Exception:
                    pass
                state.answer_translated = resp or answer_en
                return None
            except Exception:
                state.answer_translated = answer_en
                return None

        # Prefer markdown-aware translation if available.
        translator = getattr(runtime, "markdown_translator", None)
        if translator is not None:
            fn_md = getattr(translator, "translate_markdown", None)
            if callable(fn_md):
                try:
                    state.answer_translated = fn_md(answer_en)
                    return None
                except Exception:
                    pass

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
