# code_query_engine/pipeline/actions/handle_prefix.py
from __future__ import annotations

from typing import Optional, Tuple, List

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


def _match_prefix(text: str, prefix: str) -> Optional[str]:
    if not prefix:
        return None
    t = (text or "").lstrip()
    if t.startswith(prefix):
        return t[len(prefix):].strip()
    return None


class HandlePrefixAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        response = state.last_model_response or ""
        raw = step.raw

        # Collect configured prefixes: <kind>_prefix and transitions: on_<kind>
        prefix_kinds: List[Tuple[str, str]] = []
        for k, v in raw.items():
            if k.endswith("_prefix") and isinstance(v, str) and v.strip():
                kind = k[:-len("_prefix")]
                prefix_kinds.append((kind, v.strip()))

        matched_kind: Optional[str] = None
        payload: Optional[str] = None

        for kind, prefix in prefix_kinds:
            p = _match_prefix(response, prefix)
            if p is not None:
                matched_kind = kind
                payload = p
                break

        if matched_kind is None:
            # Unknown prefix => on_other or next
            return raw.get("on_other") or raw.get("next")

        # Standardize: store last payload
        if matched_kind in ("answer",):
            state.answer_en = payload or ""
            state.query_type = "direct answer"
            return raw.get("on_answer") or raw.get("next")

        if matched_kind in ("followup", "requesting_data_on", "requesting", "follow_up"):
            state.followup_query = payload or ""
            state.query_type = "vector query"
            return raw.get("on_followup") or raw.get("next")

        # Router modes
        if matched_kind in ("semantic", "bm25", "hybrid", "semantic_rerank", "direct"):
            state.retrieval_mode = matched_kind
            state.retrieval_query = payload or ""
            return raw.get(f"on_{matched_kind}") or raw.get("next")

        # Fallback: try on_<kind>, else next
        return raw.get(f"on_{matched_kind}") or raw.get("next")
