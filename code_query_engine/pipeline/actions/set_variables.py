# code_query_engine/pipeline/actions/set_variables.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


_ALLOWED_TRANSFORMS = {
    "copy",
    "to_list",
    "split_lines",
    "parse_json",
    "to_context_blocks",
    "clear",
}


def _ensure_non_empty_str(v: Any, *, err: str) -> str:
    if not isinstance(v, str):
        raise ValueError(err)
    s = v.strip()
    if not s:
        raise ValueError(err)
    return s


def _must_not_contain_dot(v: str, *, err: str) -> None:
    if "." in v:
        raise ValueError(err)


def _transform_copy(value: Any) -> Any:
    return value


def _transform_to_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value] if value.strip() else []
    raise ValueError(f"set_variables: transform 'to_list' does not support type: {type(value).__name__}")


def _transform_split_lines(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        raise ValueError(f"set_variables: transform 'split_lines' does not support type: {type(value).__name__}")

    out: List[str] = []
    for line in value.splitlines():
        t = (line or "").strip()
        if t:
            out.append(t)
    return out


def _transform_parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        raise ValueError(f"set_variables: transform 'parse_json' does not support type: {type(value).__name__}")
    try:
        return json.loads(value)
    except Exception as e:
        raise ValueError(f"set_variables: transform 'parse_json' failed to parse JSON: {e}") from e


def _transform_to_context_blocks(value: Any) -> List[str]:
    """
    Normalizes to PipelineState.context_blocks format used in this repo: List[str].
    (Your PipelineState.context_blocks is List[str], not list[dict].) :contentReference[oaicite:0]{index=0}
    """
    if value is None:
        return []

    if isinstance(value, str):
        t = value.strip()
        return [value] if t else []

    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            # allow list[str]
            if isinstance(item, str):
                t = item.strip()
                if t:
                    out.append(t)
                continue

            # allow list[dict] with {"text": "..."} (strict for key + type)
            if isinstance(item, dict):
                if "text" not in item:
                    raise ValueError("set_variables: invalid context block (missing 'text')")
                txt = item.get("text")
                if not isinstance(txt, str):
                    raise ValueError("set_variables: context block 'text' must be a string")
                t = txt.strip()
                if t:
                    out.append(t)
                continue

            raise ValueError(
                f"set_variables: transform 'to_context_blocks' does not support list element type: {type(item).__name__}"
            )

        return out

    raise ValueError(f"set_variables: transform 'to_context_blocks' does not support type: {type(value).__name__}")


def _transform_clear(dest_current_value: Any) -> Any:
    # Shortcut – deterministic only relative to current dest type.
    if isinstance(dest_current_value, list):
        return []
    if isinstance(dest_current_value, dict):
        return {}
    if isinstance(dest_current_value, str):
        return ""
    # None / missing / other => None
    return None


def _apply_transform(*, name: str, value: Any, rule_index: int, dest_current_value: Any) -> Any:
    if name not in _ALLOWED_TRANSFORMS:
        raise ValueError(f"set_variables: rule[{rule_index}] unsupported transform: {name}")

    if name == "copy":
        return _transform_copy(value)
    if name == "to_list":
        return _transform_to_list(value)
    if name == "split_lines":
        return _transform_split_lines(value)
    if name == "parse_json":
        return _transform_parse_json(value)
    if name == "to_context_blocks":
        return _transform_to_context_blocks(value)
    if name == "clear":
        return _transform_clear(dest_current_value)

    # defensive
    raise ValueError(f"set_variables: rule[{rule_index}] unsupported transform: {name}")




class SetVariablesAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "set_variables"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        rules = raw.get("rules")
        return {
            "rules_present": isinstance(rules, list),
            "rules_count": len(rules) if isinstance(rules, list) else 0,
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
        return {"next_step_id": next_step_id}

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        rules = raw.get("rules", None)

        if not isinstance(rules, list) or len(rules) == 0:
            raise ValueError("set_variables: rules must be a non-empty list")

        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise ValueError(f"set_variables: rule[{i}] must be a mapping")

            if "set" not in rule:
                raise ValueError(f"set_variables: rule[{i}] missing 'set'")

            dest = _ensure_non_empty_str(rule.get("set"), err=f"set_variables: rule[{i}] missing 'set'")
            _must_not_contain_dot(dest, err=f"set_variables: rule[{i}] 'set' must not contain '.'")

            has_from = "from" in rule
            has_value = "value" in rule

            if has_from and has_value:
                raise ValueError(f"set_variables: rule[{i}] must provide exactly one of 'from' or 'value'")
            if not has_from and not has_value:
                raise ValueError(f"set_variables: rule[{i}] must provide exactly one of 'from' or 'value'")

            if has_value:
                in_value = rule.get("value")
            else:
                src = _ensure_non_empty_str(rule.get("from"), err=f"set_variables: rule[{i}] must provide 'from' as string")
                _must_not_contain_dot(src, err=f"set_variables: rule[{i}] 'from' must not contain '.'")

                if not hasattr(state, src):
                    raise ValueError(f"set_variables: rule[{i}] source field not found on state: {src}")
                in_value = getattr(state, src)

            transform = str(rule.get("transform") or "copy").strip() or "copy"

            dest_current_value = getattr(state, dest, None)
            out = _apply_transform(name=transform, value=in_value, rule_index=i, dest_current_value=dest_current_value)

            setattr(state, dest, out)

        return None
