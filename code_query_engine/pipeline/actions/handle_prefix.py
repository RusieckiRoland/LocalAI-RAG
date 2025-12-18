# code_query_engine/pipeline/actions/handle_prefix.py
from __future__ import annotations

from typing import List, Optional, Tuple, Dict, Any

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


def _match_prefix(text: str, prefixes: Dict[str, str]) -> Tuple[Optional[str], str]:
    """Return (kind, payload) where kind is the matched prefix key and payload is the remaining text."""
    t = (text or "").strip()
    for kind, prefix in prefixes.items():
        if not prefix:
            continue
        if t.startswith(prefix):
            payload = t[len(prefix):].strip()
            return kind, payload
    return None, ""


def _parse_router_payload(payload: str) -> Tuple[Optional[str], str]:
    """Parse '<scope> | <query>' payload from the router.

    - scope: CS / SQL / ANY (optional)
    - query: the right-hand side (or the full payload if no valid scope)
    """
    p = (payload or "").strip()
    if not p:
        return None, ""

    if "|" not in p:
        return None, p

    left, right = p.split("|", 1)
    scope = left.strip().upper()
    query = right.strip()

    if scope not in ("CS", "SQL", "ANY"):
        # Not a valid scope token => treat the entire payload as query
        return None, p

    return scope, query


def _scope_to_data_types(scope: Optional[str]) -> Optional[List[str]]:
    """Map router scope to unified-index data_type filter."""
    if scope == "CS":
        return ["regular_code"]
    if scope == "SQL":
        return ["db_code"]
    if scope == "ANY":
        return ["regular_code", "db_code"]
    return None


class HandlePrefixAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}

        text = runtime.last_model_output or ""
        state.router_raw = text

        # Router mode prefixes
        semantic_prefix = raw.get("semantic_prefix")
        bm25_prefix = raw.get("bm25_prefix")
        hybrid_prefix = raw.get("hybrid_prefix")
        semantic_rerank_prefix = raw.get("semantic_rerank_prefix")
        direct_prefix = raw.get("direct_prefix")

        # Answer loop prefixes
        answer_prefix = raw.get("answer_prefix")
        followup_prefix = raw.get("followup_prefix")

        prefixes: Dict[str, str] = {
            "semantic": semantic_prefix,
            "bm25": bm25_prefix,
            "hybrid": hybrid_prefix,
            "semantic_rerank": semantic_rerank_prefix,
            "direct": direct_prefix,
            "answer": answer_prefix,
            "followup": followup_prefix,
        }

        matched_kind, payload = _match_prefix(text, prefixes)

        # Router modes
        if matched_kind in ("semantic", "bm25", "hybrid", "semantic_rerank", "direct"):
            state.retrieval_mode = matched_kind

            scope, query = _parse_router_payload(payload or "")
            state.retrieval_scope = scope
            state.retrieval_query = query

            # Soft filters derived from scope (UI "hard filters" are applied later at execution time)
            data_types = _scope_to_data_types(scope)
            state.retrieval_filters = {"data_type": data_types} if data_types else {}

            return raw.get(f"on_{matched_kind}") or raw.get("next")

        # Answer loop modes
        if matched_kind == "answer":
            state.answer_en = payload or ""
            return raw.get("on_answer") or raw.get("next")

        if matched_kind == "followup":
            state.followup_query = payload or ""
            return raw.get("on_followup") or raw.get("next")

        # Unknown => deterministic fallback
        return raw.get("on_other") or raw.get("next")
