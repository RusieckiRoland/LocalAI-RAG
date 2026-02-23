# code_query_engine/pipeline/actions/json_decision_router.py
from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


_RE_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_RE_UNQUOTED_KEY = re.compile(r"(?P<prefix>[{,]\s*)(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)\s*:")
_RE_EQUAL_ASSIGN = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)\s*=\s*")


def _strip_code_fences(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```") and t.endswith("```"):
        t = t[3:-3].strip()
        t = re.sub(r"^[A-Za-z0-9_\-]+\n", "", t)
    return t.strip()


def _try_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _try_parse_object(raw: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort parse for a JSON-ish object intended to be a dict.
    This is intentionally tolerant: it supports typical LLM mistakes.
    """
    raw = _strip_code_fences(raw)
    if not raw:
        return None

    obj = _try_json(raw)
    if isinstance(obj, dict):
        return obj

    fixed = raw.strip()

    # Wrap if missing braces but looks like key/value pairs
    if not fixed.startswith("{") and ("decision" in fixed or "query" in fixed or "filters" in fixed):
        fixed = "{" + fixed + "}"

    # Replace '=' with ':' (Python-ish dicts)
    if "=" in fixed and ":" not in fixed:
        fixed = _RE_EQUAL_ASSIGN.sub(lambda m: f'{m.group("key")}: ', fixed)

    fixed2 = _RE_UNQUOTED_KEY.sub(lambda m: f'{m.group("prefix")}"{m.group("key")}":', fixed)
    fixed = fixed2

    fixed2 = _RE_TRAILING_COMMA.sub(r"\1", fixed)
    fixed = fixed2

    obj = _try_json(fixed)
    if isinstance(obj, dict):
        return obj

    try:
        obj = ast.literal_eval(fixed)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None

    return None


def _norm_decision(s: Any) -> str:
    return str(s or "").strip().lower()


class JsonDecisionRouterAction(PipelineActionBase):
    """
    Routes based on a JSON decision emitted by the model.

    Input: state.last_model_response (string)

    Step raw contract:
      routes: { "<decision>": "<next_step_id>", ... }   (non-empty)
      on_other: "<next_step_id>"                         (required)

    Decision keys supported (first match wins):
      - decision
      - route
      - mode

    If the chosen route is a retrieval/search route, you typically want to strip the decision key
    and leave a clean payload for downstream parsing. This action does that by default:
      - it removes decision/route/mode keys and writes the remaining object back into state.last_model_response
        as a compact JSON string.
    """

    action_id = "json_decision_router"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        routes = raw.get("routes")
        return {
            "payload_len": len((state.last_model_response or "") or ""),
            "routes_count": len(routes) if isinstance(routes, dict) else 0,
            "on_other": raw.get("on_other"),
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
        return {"next_step_id": next_step_id, "error": error}

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        routes = raw.get("routes")
        if not isinstance(routes, dict) or not routes:
            raise ValueError("json_decision_router: routes must be a non-empty dict")

        on_other = str(raw.get("on_other") or "").strip()
        if not on_other:
            raise ValueError("json_decision_router: on_other is required")

        payload = (state.last_model_response or "").strip()
        obj = _try_parse_object(payload)
        if not isinstance(obj, dict):
            return on_other

        decision = _norm_decision(obj.get("decision"))
        if not decision:
            decision = _norm_decision(obj.get("route"))
        if not decision:
            decision = _norm_decision(obj.get("mode"))

        # Clean payload for downstream (remove routing keys, keep retrieval fields).
        cleaned = dict(obj)
        cleaned.pop("decision", None)
        cleaned.pop("route", None)
        cleaned.pop("mode", None)
        state.last_model_response = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

        target = str(routes.get(decision) or "").strip() if decision else ""
        if target:
            return target

        return on_other

