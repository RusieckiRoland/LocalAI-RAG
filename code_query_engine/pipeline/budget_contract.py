# code_query_engine/pipeline/budget_contract.py
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .definitions import PipelineDef, StepDef
from .loader import PipelineLoader

py_logger = logging.getLogger(__name__)


_POLICY_FAIL_FAST = "fail_fast"
_POLICY_AUTO_CLAMP = "auto_clamp"


def normalize_limits_policy(v: str | None) -> str:
    s = str(v or "").strip().lower()
    if s in (_POLICY_FAIL_FAST, _POLICY_AUTO_CLAMP):
        return s
    return ""


@dataclass(frozen=True)
class BudgetContractClamp:
    kind: str
    step_id: Optional[str]
    before: int
    after: int
    reason: str


@dataclass(frozen=True)
class BudgetContractResult:
    policy: str
    pipeline_name: str
    model_context_window: int
    prompts_dir: str
    max_context_tokens_before: int
    max_context_tokens_after: int
    max_history_tokens: int
    clamps: List[BudgetContractClamp]
    files: List[str]


def _as_int(v: Any, *, key: str) -> int:
    try:
        return int(v)
    except Exception as ex:
        raise ValueError(f"budget_contract: {key} must be int") from ex


def _token_count(token_counter: Any, text: str) -> int:
    if token_counter is None:
        return 0
    fn = getattr(token_counter, "token_count", None)
    if not callable(fn):
        return 0
    return int(fn(text or ""))


def _load_prompt_text(*, prompts_dir: str, prompt_key: str) -> str:
    rel = f"{prompt_key}.txt"
    path = os.path.join(prompts_dir, rel)
    if not os.path.isfile(path):
        raise ValueError(f"budget_contract: prompt file not found: {path}")
    return Path(path).read_text(encoding="utf-8")


def _user_parts_wrappers_text(step: StepDef) -> str:
    raw = step.raw or {}
    user_parts_cfg = raw.get("user_parts")
    if not isinstance(user_parts_cfg, dict) or not user_parts_cfg:
        return ""
    out: list[str] = []
    for _name, spec in user_parts_cfg.items():
        if not isinstance(spec, dict):
            continue
        template = spec.get("template")
        if isinstance(template, str) and "{}" in template:
            out.append(template.format(""))
    return "".join(out)


def _pipeline_prompt_keys(pipeline: PipelineDef) -> List[str]:
    keys: list[str] = []
    for s in pipeline.steps:
        if s.action != "call_model":
            continue
        pk = str((s.raw or {}).get("prompt_key") or "").strip()
        if pk:
            keys.append(pk)
    # stable order
    return sorted(set(keys))


def _fingerprint_paths(paths: Iterable[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for p in paths:
        try:
            out[p] = float(os.path.getmtime(p))
        except Exception:
            # Missing files should be handled elsewhere; still include to force recompute.
            out[p] = -1.0
    return out


def _resolve_pipeline_files(*, loader: PipelineLoader, pipeline_name: str) -> List[str]:
    files = loader.resolve_files_by_name(pipeline_name)
    return [os.fspath(p) for p in files]


def enforce_budget_contract(
    *,
    loader: PipelineLoader,
    pipeline: PipelineDef,
    effective_settings: Dict[str, Any],
    model_context_window: int,
    model_default_max_tokens: int,
    token_counter: Any,
    policy: str,
) -> Tuple[PipelineDef, Dict[str, Any], BudgetContractResult, Dict[str, float]]:
    """
    Enforces a simple budget contract for a single pipeline run (in-memory only).

    Rules:
    - Never writes to YAML files.
    - In fail_fast mode: raises ValueError on conflicts.
    - In auto_clamp mode: clamps in-memory (step max_output_tokens and/or max_context_tokens) and logs warnings.
    """

    pol = normalize_limits_policy(policy) or _POLICY_FAIL_FAST

    n_ctx = _as_int(model_context_window, key="model_context_window")
    if n_ctx <= 0:
        raise ValueError("budget_contract: model_context_window must be > 0")

    prompts_dir = str(effective_settings.get("prompts_dir") or "prompts")

    max_context_tokens = _as_int(effective_settings.get("max_context_tokens"), key="settings.max_context_tokens")
    if max_context_tokens <= 0:
        raise ValueError("budget_contract: settings.max_context_tokens must be > 0")

    max_history_tokens = int(effective_settings.get("max_history_tokens") or 0)
    if max_history_tokens < 0:
        raise ValueError("budget_contract: settings.max_history_tokens must be >= 0")

    safety_margin = int(effective_settings.get("budget_safety_margin_tokens") or 128)
    if safety_margin < 0:
        raise ValueError("budget_contract: settings.budget_safety_margin_tokens must be >= 0")

    # Compute per-step reserves (best-effort). If token_counter is missing, we use conservative fallback.
    per_step_fixed_prompt_tokens: dict[str, int] = {}
    any_history_used = False

    for step in pipeline.steps:
        if step.action != "call_model":
            continue
        raw = step.raw or {}
        prompt_key = str(raw.get("prompt_key") or "").strip()
        use_history = bool(raw.get("use_history", False))
        any_history_used = any_history_used or use_history

        # If token_counter is missing, we can only apply coarse numeric checks.
        fixed_tokens = 1000 if token_counter is None else 0
        if prompt_key and token_counter is not None:
            sys_txt = _load_prompt_text(prompts_dir=prompts_dir, prompt_key=prompt_key)
            wrappers = _user_parts_wrappers_text(step)
            fixed_tokens = _token_count(token_counter, sys_txt + "\n\n" + wrappers)
            # Minimal overhead for [INST]/role wrappers; conservative.
            fixed_tokens += 64
        per_step_fixed_prompt_tokens[step.id] = int(fixed_tokens)

    if any_history_used and max_history_tokens == 0:
        msg = (
            "budget_contract: at least one call_model step uses history, but settings.max_history_tokens is 0/missing. "
            "Set settings.max_history_tokens to a safe cap."
        )
        if pol == _POLICY_FAIL_FAST:
            raise ValueError(msg)
        py_logger.warning(msg)

    # Determine per-step requested max output tokens (as configured) for constraints.
    def _step_requested_out_tokens(step: StepDef) -> int:
        raw = step.raw or {}
        if raw.get("max_output_tokens") is not None:
            return int(raw.get("max_output_tokens"))
        if raw.get("max_tokens") is not None:
            return int(raw.get("max_tokens"))
        return int(model_default_max_tokens)

    call_model_steps = [s for s in pipeline.steps if s.action == "call_model"]

    if not call_model_steps:
        files = _resolve_pipeline_files(loader=loader, pipeline_name=pipeline.name)
        fp = _fingerprint_paths(files)
        result = BudgetContractResult(
            policy=pol,
            pipeline_name=pipeline.name,
            model_context_window=n_ctx,
            prompts_dir=prompts_dir,
            max_context_tokens_before=max_context_tokens,
            max_context_tokens_after=max_context_tokens,
            max_history_tokens=max_history_tokens,
            clamps=[],
            files=files,
        )
        return pipeline, effective_settings, result, fp

    # First: enforce global max_context_tokens across all call_model steps (worst-case).
    # We require: fixed_prompt + max_history_tokens + max_context_tokens + out_tokens + safety <= n_ctx
    max_context_allowed = None
    for step in call_model_steps:
        fixed_tokens = per_step_fixed_prompt_tokens.get(step.id, 1000)
        out_tokens = _step_requested_out_tokens(step)
        allowed = n_ctx - int(fixed_tokens) - int(max_history_tokens) - int(out_tokens) - int(safety_margin)
        if max_context_allowed is None or allowed < max_context_allowed:
            max_context_allowed = allowed

    if max_context_allowed is None:
        max_context_allowed = max_context_tokens

    clamps: list[BudgetContractClamp] = []
    max_context_tokens_after = max_context_tokens

    if max_context_tokens_after > max_context_allowed:
        msg = (
            f"budget_contract: settings.max_context_tokens={max_context_tokens_after} exceeds allowed={max_context_allowed} "
            f"for model_context_window={n_ctx} (consider history/output/prompt overhead)."
        )
        if pol == _POLICY_FAIL_FAST:
            raise ValueError(msg)
        new_v = max(0, int(max_context_allowed))
        clamps.append(
            BudgetContractClamp(
                kind="max_context_tokens",
                step_id=None,
                before=int(max_context_tokens_after),
                after=int(new_v),
                reason=msg,
            )
        )
        py_logger.warning("%s Applying clamp: %s -> %s", msg, max_context_tokens_after, new_v)
        max_context_tokens_after = new_v

    if max_context_tokens_after <= 0:
        raise ValueError(
            "budget_contract: resolved max_context_tokens_after <= 0. "
            "Increase model_context_window or decrease history/output budgets."
        )

    # Apply (in-memory) clamp to effective settings.
    eff2 = dict(effective_settings)
    eff2["max_context_tokens"] = int(max_context_tokens_after)

    # Second: per-step output clamp if still impossible (rare but can happen with fixed prompt too large).
    new_steps: list[StepDef] = []
    for step in pipeline.steps:
        if step.action != "call_model":
            new_steps.append(step)
            continue

        fixed_tokens = per_step_fixed_prompt_tokens.get(step.id, 1000)
        requested_out = _step_requested_out_tokens(step)
        allowed_out = n_ctx - int(fixed_tokens) - int(max_history_tokens) - int(max_context_tokens_after) - int(safety_margin)

        if requested_out <= allowed_out:
            new_steps.append(step)
            continue

        msg = (
            f"budget_contract: call_model step '{step.id}' requested max_output_tokens={requested_out} but allowed={allowed_out} "
            f"(n_ctx={n_ctx} fixed_prompt={fixed_tokens} history={max_history_tokens} context={max_context_tokens_after} safety={safety_margin})."
        )
        if pol == _POLICY_FAIL_FAST:
            raise ValueError(msg)

        new_out = max(0, int(allowed_out))
        if new_out <= 0:
            raise ValueError(msg + " Cannot auto-clamp: allowed_out <= 0.")

        raw2 = dict(step.raw or {})
        raw2["max_output_tokens"] = int(new_out)
        # Remove ambiguity if max_tokens existed.
        raw2.pop("max_tokens", None)
        clamps.append(
            BudgetContractClamp(
                kind="max_output_tokens",
                step_id=step.id,
                before=int(requested_out),
                after=int(new_out),
                reason=msg,
            )
        )
        py_logger.warning("%s Applying clamp: %s -> %s", msg, requested_out, new_out)
        new_steps.append(StepDef(id=step.id, action=step.action, raw=raw2))

    pipe2 = PipelineDef(name=pipeline.name, settings=pipeline.settings, steps=new_steps)

    # Fingerprint for caching: YAML chain + referenced prompt files.
    files = _resolve_pipeline_files(loader=loader, pipeline_name=pipeline.name)
    for pk in _pipeline_prompt_keys(pipeline):
        files.append(os.path.join(prompts_dir, f"{pk}.txt"))
    fp = _fingerprint_paths(files)

    result = BudgetContractResult(
        policy=pol,
        pipeline_name=pipeline.name,
        model_context_window=n_ctx,
        prompts_dir=prompts_dir,
        max_context_tokens_before=max_context_tokens,
        max_context_tokens_after=max_context_tokens_after,
        max_history_tokens=max_history_tokens,
        clamps=clamps,
        files=files,
    )
    return pipe2, eff2, result, fp

