# code_query_engine/pipeline/actions/prefix_router.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


def _match_prefix(text: str, prefixes: Dict[str, str]) -> Tuple[Optional[str], str]:
    """
    Return (kind, payload) where kind is matched kind (e.g. 'bm25') and payload is the remaining text.
    If no prefix matches -> (None, full_text_stripped).
    """
    t = (text or "").strip()
    for kind, prefix in (prefixes or {}).items():
        p = (prefix or "").strip()
        if not p:
            continue
        if t.startswith(p):
            return kind, t[len(p) :].strip()
    return None, t


def _collect_routes(raw: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Read step.raw["routes"] in the new (Option B) format and return:
      - prefixes: {kind: prefix}
      - next_map: {kind: next_step_id}

    Expected YAML shape:

      routes:
        bm25:
          prefix: "[BM25:]"
          next: fetch
        semantic:
          prefix: "[SEMANTIC:]"
          next: fetch
      on_other: fallback_step
    """
    raw = raw or {}
    routes = raw.get("routes")

    prefixes: Dict[str, str] = {}
    next_map: Dict[str, str] = {}

    if not isinstance(routes, dict):
        return prefixes, next_map

    for kind, cfg in routes.items():
        if not isinstance(kind, str):
            continue
        k = kind.strip()
        if not k:
            continue
        if not isinstance(cfg, dict):
            continue

        prefix = str(cfg.get("prefix") or "")
        next_step = str(cfg.get("next") or "")

        prefixes[k] = prefix
        next_map[k] = next_step

    return prefixes, next_map


def _validate_step_contract(raw: Dict[str, Any], prefixes: Dict[str, str], next_map: Dict[str, str]) -> None:
    """
    Strict contract (no magic fallbacks), Option B routes format:

    - routes must be present and be a non-empty dict
    - for every route kind:
        - prefix must be present and non-empty (after strip)
        - next must be present and non-empty (after strip)
        - prefix must be a string-like value (we coerce but still require non-empty)
    - if no prefix matches at runtime, on_other is REQUIRED (no implicit "next")
    """
    raw = raw or {}

    routes = raw.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise ValueError("prefix_router step must define non-empty 'routes'.")

    # validate each route entry
    for kind in routes.keys():
        k = str(kind or "").strip()
        if not k:
            raise ValueError("prefix_router step has an empty route kind in 'routes'.")

        p = str(prefixes.get(k) or "").strip()
        if not p:
            raise ValueError(
                f"prefix_router step is inconsistent: routes['{k}'].prefix is missing or empty."
            )

        n = str(next_map.get(k) or "").strip()
        if not n:
            raise ValueError(
                f"prefix_router step is inconsistent: routes['{k}'].next is missing or empty."
            )

    # require on_other (no implicit next)
    if not str(raw.get("on_other") or "").strip():
        raise ValueError("prefix_router step must define 'on_other' (no implicit next fallback).")


class PrefixRouterAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "prefix_router"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        text = (state.last_model_response or "").strip()
        prefixes, next_map = _collect_routes(raw)

        return {
            "text": text,
            "routes": {
                k: {"prefix": v, "next": next_map.get(k, "")}
                for k, v in prefixes.items()
                if (v or "").strip()
            },
            "last_prefix_before": getattr(state, "last_prefix", None),
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
            "last_prefix": getattr(state, "last_prefix", None),
            "payload_after_strip": (state.last_model_response or ""),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}

        # Always route based on the incoming text.
        text = (state.last_model_response or "").strip()

        prefixes, next_map = _collect_routes(raw)
        _validate_step_contract(raw, prefixes, next_map)

        matched_kind, payload = _match_prefix(text, prefixes)

        if matched_kind:
            # Save the matched prefix kind (NOT the literal prefix string).
            state.last_prefix = matched_kind

            # Strip prefix from the text and store the payload back into state.
            state.last_model_response = payload

            return str(next_map.get(matched_kind) or "").strip() or None

        # No match -> keep full text as-is and route to on_other.
        # (Contract guarantees on_other exists.)
        state.last_prefix = ""
        state.last_model_response = text
        return str(raw.get("on_other") or "").strip() or None
