from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase

_RE_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_RE_UNQUOTED_KEY = re.compile(r"(?P<prefix>[{,]\s*)(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)\s*:")


def _strip_code_fences(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```") and t.endswith("```"):
        t = t[3:-3].strip()
        t = re.sub(r"^[A-Za-z0-9_\-]+\n", "", t)
    return t.strip()


def _try_parse_object(raw: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    if not raw.strip():
        return None, ["empty payload"]

    # 1) Strict JSON
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None, warnings
    except Exception:
        pass

    fixed = raw.strip()
    # Quote unquoted keys.
    fixed2 = _RE_UNQUOTED_KEY.sub(lambda m: f'{m.group("prefix")}"{m.group("key")}":', fixed)
    if fixed2 != fixed:
        fixed = fixed2
        warnings.append("quoted unquoted keys")

    # Remove trailing commas.
    fixed2 = _RE_TRAILING_COMMA.sub(r"\1", fixed)
    if fixed2 != fixed:
        fixed = fixed2
        warnings.append("removed trailing commas")

    # 2) JSON after repairs
    try:
        obj = json.loads(fixed)
        return obj if isinstance(obj, dict) else None, warnings
    except Exception:
        pass

    # 3) Python literal (single quotes, etc.)
    try:
        obj = ast.literal_eval(fixed)
        if isinstance(obj, dict):
            return obj, warnings + ["parsed via ast.literal_eval"]
        return None, warnings + ["parsed non-dict object; ignoring"]
    except Exception:
        return None, warnings + ["could not parse payload as object"]


def _coerce_rules(raw_rules: Any) -> Dict[str, Dict[str, Any]]:
    """
    Normalize rules config into:
        { "<target_step_id>": {"topic": "...", "allow_keys": [...], "rename": {...}} }
    """
    if raw_rules is None:
        return {}
    if not isinstance(raw_rules, dict):
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for k, v in raw_rules.items():
        target = str(k or "").strip()
        if not target or not isinstance(v, dict):
            continue
        out[target] = dict(v)
    return out


def _extract_directives(obj: Dict[str, Any], directives_key: str) -> List[Dict[str, Any]]:
    v = obj.get(directives_key, None)
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []


class InboxDispatcherAction(PipelineActionBase):
    """
    Reads the last model response (JSON object) and enqueues allowlisted "directives" into the per-run inbox.

    This enables dynamic, model-suggested configuration for downstream actions without coupling parameters
    to retrieval_filters or other security-sensitive fields.

    Step.raw contract:
      - directives_key: str (default "dispatch")
      - rules: dict keyed by target_step_id:
          <target_step_id>:
            topic: str (default "config")
            allow_keys: [str, ...] (required to allow anything)
            rename: {from_key: to_key, ...} (optional)

    JSON directive schema (in model output):
      {
        "dispatch": [
          {
            "target_step_id": "fetch_node_texts",
            "topic": "config",              (optional)
            "payload": { ... }              (optional; may also use direct keys)
          }
        ]
      }

    Accepted aliases for target: target_step_id | target | id
    """

    @property
    def action_id(self) -> str:
        return "inbox_dispatcher"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        return {
            "directives_key": str(raw.get("directives_key") or "dispatch"),
            "rules_targets": sorted(list(_coerce_rules(raw.get("rules")).keys())),
            "payload_preview": str((state.last_model_response or "")[:200]),
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
        directives_key = str(raw.get("directives_key") or "dispatch").strip() or "dispatch"
        rules = _coerce_rules(raw.get("rules"))

        payload_raw = _strip_code_fences(state.last_model_response or "")
        obj, _warnings = _try_parse_object(payload_raw)
        if not obj:
            return None

        directives = _extract_directives(obj, directives_key=directives_key)
        if not directives:
            return None

        for d in directives:
            target = (
                str(d.get("target_step_id") or d.get("target") or d.get("id") or "").strip()
            )
            if not target:
                continue
            rule = rules.get(target)
            if not isinstance(rule, dict):
                continue

            topic = str(d.get("topic") or rule.get("topic") or "config").strip() or "config"
            allow_keys = rule.get("allow_keys", None)
            if not isinstance(allow_keys, list) or not allow_keys:
                continue
            allow_set = {str(k).strip() for k in allow_keys if str(k).strip()}
            if not allow_set:
                continue

            rename = rule.get("rename", None)
            rename_map: Dict[str, str] = {}
            if isinstance(rename, dict):
                for fk, tk in rename.items():
                    fks = str(fk or "").strip()
                    tks = str(tk or "").strip()
                    if fks and tks:
                        rename_map[fks] = tks

            raw_payload = d.get("payload", None)
            if isinstance(raw_payload, dict):
                candidate = dict(raw_payload)
            else:
                # Allow shorthand: directive can place keys directly (besides routing keys)
                candidate = {
                    k: v
                    for k, v in d.items()
                    if k not in ("target_step_id", "target", "id", "topic", "payload")
                }

            filtered: Dict[str, Any] = {}
            for k, v in candidate.items():
                ks = str(k or "").strip()
                if not ks:
                    continue
                if ks not in allow_set:
                    continue
                out_key = rename_map.get(ks, ks)
                filtered[out_key] = v

            if not filtered:
                continue

            state.enqueue_message(
                target_step_id=target,
                topic=topic,
                payload=filtered,
                sender_step_id=step.id,
            )

        return None
