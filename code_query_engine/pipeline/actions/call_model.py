from __future__ import annotations

from pathlib import Path
import os
from typing import Optional, Any, Dict, Tuple

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from .base_action import PipelineActionBase


class CallModelAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "call_model"

    # ------------------------------------------------------------------ #
    # Prompt building (single source of truth)
    # ------------------------------------------------------------------ #

    B_INST = "[INST]"
    E_INST = "[/INST]"
    B_SYS = "<<SYS>>\n"
    E_SYS = "\n<</SYS>>\n\n"

    def _escape_control_tokens(self, text: str) -> str:
        """
        Escape CodeLlama prompt-template control tokens inside user-controlled text.
        This prevents a user from closing/opening template blocks or injecting sys blocks.
        """
        if not text:
            return text

        return (
            text.replace(self.E_INST, "[/I N S T]")
            .replace(self.B_INST, "[I N S T]")
            .replace("<<SYS>>", "< <SYS> >")
            .replace("<</SYS>>", "< </SYS> >")
        )

    def _inject_constants(self, runtime: PipelineRuntime, template: str) -> str:
        """
        Inject placeholders like {ANSWER_PREFIX}/{FOLLOWUP_PREFIX} if present.
        Uses runtime.constants when available (preferred).
        """
        t = template or ""

        constants_obj = getattr(runtime, "constants", None)
        if constants_obj is not None:
            answer_prefix = getattr(constants_obj, "ANSWER_PREFIX", None)
            followup_prefix = getattr(constants_obj, "FOLLOWUP_PREFIX", None)

            if isinstance(answer_prefix, str):
                t = t.replace("{ANSWER_PREFIX}", answer_prefix)
            if isinstance(followup_prefix, str):
                t = t.replace("{FOLLOWUP_PREFIX}", followup_prefix)

        return t

    def _resolve_prompt_template(self, consultant_for_prompt: str) -> Dict[str, Any]:
        """
        Resolve prompt template from filesystem: PROMPTS_DIR/<key>.txt
        Key is typically like: rejewski/router_v1
        """
        result: Dict[str, Any] = {
            "prompt_template_raw": None,
            "prompt_template": None,
            "prompt_template_found": False,
            "prompt_template_source": None,
            "prompt_template_error": None,
        }

        key = (consultant_for_prompt or "").strip()
        if not key:
            return result

        try:
            prompts_dir = os.environ.get("PROMPTS_DIR", "prompts")
            base = Path(prompts_dir)

            rel = Path(*key.split("/"))
            candidates = [
                base / (str(rel) + ".txt"),
                base / rel / "prompt.txt",
                base / rel,  # allow exact path if user passes extension
            ]

            for path in candidates:
                if path.exists() and path.is_file():
                    raw = path.read_text(encoding="utf-8")
                    if raw.strip():
                        result.update(
                            {
                                "prompt_template_raw": raw,
                                "prompt_template_found": True,
                                "prompt_template_source": f"file:{path.as_posix()}",
                            }
                        )
                        return result
        except Exception as ex:
            result["prompt_template_error"] = f"filesystem: {type(ex).__name__}: {ex}"

        return result

    def _build_full_prompt(
        self,
        *,
        runtime: PipelineRuntime,
        consultant_for_prompt: str,
        composed_context: str,
        model_input_en: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Build the exact prompt string that is passed to llama_cpp (truth for logging).
        """
        tpl_info = self._resolve_prompt_template(consultant_for_prompt)

        template_raw = tpl_info.get("prompt_template_raw") or ""
        template_injected = self._inject_constants(runtime, template_raw)

        safe_context = self._escape_control_tokens(composed_context or "")
        safe_question = self._escape_control_tokens(model_input_en or "")

        sys_block = ""
        if template_injected.strip():
            sys_block = self.B_SYS + template_injected.strip() + self.E_SYS

        user_content = (
            f"### Context:\n{safe_context.strip() or '(none)'}\n\n"
            f"### User:\n{safe_question.strip()}\n"
        )

        rendered_prompt = f"{self.B_INST}{sys_block}{user_content}{self.E_INST}"

        log_payload: Dict[str, Any] = {
            "prompt_template_raw": template_raw if template_raw.strip() else None,
            "prompt_template": template_injected if template_injected.strip() else None,
            "prompt_template_found": bool(tpl_info.get("prompt_template_found")),
            "prompt_template_source": tpl_info.get("prompt_template_source"),
            "prompt_template_error": tpl_info.get("prompt_template_error"),
            "rendered_prompt": rendered_prompt,
        }

        return rendered_prompt, log_payload

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        prompt_key = (raw.get("prompt_key") or "").strip()
        consultant_for_prompt = prompt_key or state.consultant

        # This is the real context used for the prompt (history + retrieved context).
        composed_context = state.composed_context_for_prompt()
        model_input_en = state.model_input_en_or_fallback()

        rendered_prompt, prompt_log = self._build_full_prompt(
            runtime=runtime,
            consultant_for_prompt=consultant_for_prompt,
            composed_context=composed_context,
            model_input_en=model_input_en,
        )

        # Keep raw parts for debugging.
        history_context = state.history_for_prompt()

        return {
            "prompt_key": prompt_key,
            "consultant_for_prompt": consultant_for_prompt,
            "history_context": history_context,
            "composed_context": composed_context,
            "model_input_en": model_input_en,
            # Truth: exact string passed into llama_cpp
            **prompt_log,
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
            "last_model_response": state.last_model_response,
        }

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        prompt_key = (raw.get("prompt_key") or "").strip()
        consultant_for_prompt = prompt_key or state.consultant

        composed_context = state.composed_context_for_prompt()
        model_input_en = state.model_input_en_or_fallback()

        state.next_codellama_prompt = consultant_for_prompt

        rendered_prompt, _ = self._build_full_prompt(
            runtime=runtime,
            consultant_for_prompt=consultant_for_prompt,
            composed_context=composed_context,
            model_input_en=model_input_en,
        )

        # New API: model gets a ready prompt. No backward compatibility.
        response = runtime.main_model.ask(prompt=rendered_prompt)

        state.last_model_response = response
        return None
