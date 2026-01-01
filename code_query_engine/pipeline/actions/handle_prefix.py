# code_query_engine/pipeline/actions/handle_prefix.py
from __future__ import annotations

from typing import List, Optional, Tuple, Dict, Any

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from .base_action import PipelineActionBase


def _match_prefix(text: str, prefixes: Dict[str, str]) -> Tuple[Optional[str], str]:
    """Return (kind, payload) where kind is the matched prefix key and payload is the remaining text."""
    t = (text or "").strip()
    for kind, prefix in prefixes.items():
        if not prefix:
            continue
        if t.startswith(prefix):
            return kind, t[len(prefix) :].strip()
    return None, t


def _parse_router_payload(payload: str) -> Tuple[Optional[str], str]:
    """Parse '<scope> | <query>' payload.

    - scope: CS / SQL / ANY (optional)
    - query: right-hand side (or the full payload if no valid scope)
    """
    p = (payload or "").strip()
    if "|" not in p:
        return None, p

    left, right = p.split("|", 1)
    scope = left.strip().upper()
    query = right.strip()

    if scope not in ("CS", "SQL", "ANY"):
        return None, p
    return scope, query


def _scope_to_data_types(scope: Optional[str]) -> Optional[List[str]]:
    """Map scope token to unified-index data_type filter."""
    if scope == "CS":
        return ["regular_code"]
    if scope == "SQL":
        return ["db_code"]
    if scope == "ANY":
        return ["regular_code", "db_code"]
    return None


class HandlePrefixAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "handle_prefix"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        text = getattr(runtime, "last_model_output", None) or state.last_model_response or ""
        text = (text or "").strip()
        return {
            "text": text,
            "raw_prefix_config": {
                "semantic_prefix": raw.get("semantic_prefix"),
                "bm25_prefix": raw.get("bm25_prefix"),
                "hybrid_prefix": raw.get("hybrid_prefix"),
                "semantic_rerank_prefix": raw.get("semantic_rerank_prefix"),
                "direct_prefix": raw.get("direct_prefix"),
                "answer_prefix": raw.get("answer_prefix"),
                "followup_prefix": raw.get("followup_prefix"),
                "ready_prefix": raw.get("ready_prefix"),
            },
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
            "query_type": state.query_type,
            "retrieval_mode": state.retrieval_mode,
            "retrieval_scope": state.retrieval_scope,
            "retrieval_query": state.retrieval_query,
            "retrieval_filters": state.retrieval_filters,
            "followup_query": state.followup_query,
            "answer_en": state.answer_en,
            "router_raw": state.router_raw,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}

        # Support older tests that pass runtime.last_model_output,
        # while production uses state.last_model_response.
        text = getattr(runtime, "last_model_output", None) or state.last_model_response or ""
        text = (text or "").strip()

        state.router_raw = state.router_raw or text

        # Router / assessor mode prefixes
        semantic_prefix = raw.get("semantic_prefix")
        bm25_prefix = raw.get("bm25_prefix")
        hybrid_prefix = raw.get("hybrid_prefix")
        semantic_rerank_prefix = raw.get("semantic_rerank_prefix")
        direct_prefix = raw.get("direct_prefix")

        # Answer loop prefixes (simple pipeline)
        answer_prefix = raw.get("answer_prefix")
        followup_prefix = raw.get("followup_prefix")

        # Assessment prefix
        ready_prefix = raw.get("ready_prefix")

        prefixes: Dict[str, str] = {
            "ready": ready_prefix,
            "semantic": semantic_prefix,
            "bm25": bm25_prefix,
            "hybrid": hybrid_prefix,
            "semantic_rerank": semantic_rerank_prefix,
            "direct": direct_prefix,
            "answer": answer_prefix,
            "followup": followup_prefix,
        }

        matched_kind, payload = _match_prefix(text, prefixes)

        if matched_kind and matched_kind != "other":
            query_type_map = {"semantic_rerank": "SEMANTIC_RERANK"}
            state.query_type = query_type_map.get(matched_kind, matched_kind.upper())


        # Router / assessor retrieval modes
        if matched_kind in ("semantic", "bm25", "hybrid", "semantic_rerank"):
            state.retrieval_mode = matched_kind
            scope, query = _parse_router_payload(payload or "")
            state.retrieval_scope = scope
            state.retrieval_query = query

            data_types = _scope_to_data_types(scope)
            state.retrieval_filters = {"data_type": data_types} if data_types else {}

            return raw.get(f"on_{matched_kind}") or raw.get("next")

        # Direct: skip retrieval (router only)
        if matched_kind == "direct":
            return raw.get("on_direct") or raw.get("next")

        # Simple pipeline: final answer / followup
        if matched_kind == "answer":
            state.answer_en = payload or ""
            return raw.get("on_answer") or raw.get("next")

        if matched_kind == "followup":
            state.followup_query = payload or ""
            return raw.get("on_followup") or raw.get("next")

        # Assessment pipeline: accept draft answer as final
        if matched_kind == "ready":
            if payload and payload.strip():
                state.answer_en = payload.strip()
            else:
                # Default: accept draft answer prepared by the answerer step.
                from_key = (raw.get("ready_from_state") or "").strip()
                if from_key:
                    state.answer_en = (getattr(state, from_key, "") or "").strip()
                else:
                    state.answer_en = (state.draft_answer_en or "").strip()
            return raw.get("on_ready") or raw.get("next")

        # Unknown => deterministic fallback
        return raw.get("on_other") or raw.get("next")
