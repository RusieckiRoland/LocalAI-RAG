# code_query_engine/pipeline/actions/handle_prefix.py
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


def _collect_prefixes(raw: Dict[str, Any]) -> Dict[str, str]:
    """
    Collect all <kind>_prefix fields from step.raw into a {kind: prefix} dict.
    Example: bm25_prefix -> {"bm25": "..."}
    """
    out: Dict[str, str] = {}
    for k, v in (raw or {}).items():
        if not isinstance(k, str):
            continue
        if not k.endswith("_prefix"):
            continue
        kind = k[: -len("_prefix")].strip()
        if not kind:
            continue
        out[kind] = str(v or "")
    return out


def _validate_step_contract(raw: Dict[str, Any], prefixes: Dict[str, str]) -> None:
    """
    Strict contract (no magic fallbacks):

    - For every <kind>_prefix we REQUIRE on_<kind> to be present and non-empty.
    - For every on_<kind> we REQUIRE <kind>_prefix to be present (except on_other).
    - If no prefix matches at runtime, we REQUIRE on_other (no implicit "next").
    """
    raw = raw or {}
    prefixes = prefixes or {}

    # prefix -> on_kind
    for kind in prefixes.keys():
        on_key = f"on_{kind}"
        if not str(raw.get(on_key) or "").strip():
            raise ValueError(
                f"handle_prefix step is inconsistent: '{kind}_prefix' present but missing '{on_key}'."
            )

    # on_kind -> prefix (except on_other)
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if not k.startswith("on_"):
            continue
        if k == "on_other":
            continue
        kind = k[len("on_") :].strip()
        if not kind:
            continue
        if kind not in prefixes:
            raise ValueError(
                f"handle_prefix step is inconsistent: '{k}' present but missing '{kind}_prefix'."
            )

    # require on_other (no implicit next)
    if not str(raw.get("on_other") or "").strip():
        raise ValueError("handle_prefix step must define 'on_other' (no implicit next fallback).")


class HandlePrefixAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "handle_prefix"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        text = (getattr(runtime, "last_model_output", None) or state.last_model_response or "").strip()
        prefixes = _collect_prefixes(raw)
        return {
            "text": text,
            "prefixes": {k: v for k, v in prefixes.items() if (v or "").strip()},
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
        text = (getattr(runtime, "last_model_output", None) or state.last_model_response or "").strip()

        prefixes = _collect_prefixes(raw)
        _validate_step_contract(raw, prefixes)

        matched_kind, payload = _match_prefix(text, prefixes)

        if matched_kind:
            # Save the matched prefix kind (NOT the literal prefix string).
            state.last_prefix = matched_kind

            # Strip prefix from the text and store the payload back into state.
            state.last_model_response = payload

            return str(raw.get(f"on_{matched_kind}") or "").strip() or None

        # No match -> keep full text as-is and route to on_other.
        # (Contract guarantees on_other exists.)
        state.last_prefix = ""
        state.last_model_response = text
        return str(raw.get("on_other") or "").strip() or None
