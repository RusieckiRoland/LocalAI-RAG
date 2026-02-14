# code_query_engine/pipeline/actions/repeat_query_guard.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..query_parsers import BaseQueryParser, QueryParseResult, JsonishQueryParser
from ..state import PipelineState
from .base_action import PipelineActionBase


def _norm(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def _resolve_parser(parser_name: str) -> BaseQueryParser:
    name = str(parser_name or "").strip()
    if not name:
        return JsonishQueryParser()
    if name == "JsonishQueryParser":
        return JsonishQueryParser()
    p = JsonishQueryParser()
    if name == p.parser_id:
        return p
    raise ValueError(f"repeat_query_guard: Unknown query_parser '{name}'. Supported: JsonishQueryParser / jsonish_v1")


def _parse_payload(step_raw: Dict[str, Any], payload: str) -> Tuple[str, List[str]]:
    parser_name = str(step_raw.get("query_parser") or "").strip()
    if not parser_name:
        # Best-effort: treat raw string as the query.
        return (payload or "").strip(), []
    parser = _resolve_parser(parser_name)
    result: QueryParseResult = parser.parse(payload or "")
    return (result.query or "").strip(), list(result.warnings or [])


class RepeatQueryGuardAction(PipelineActionBase):
    """
    Prevents re-issuing the same retrieval query within a single pipeline run.

    It inspects state.last_model_response (expected to be JSON-ish payload after prefix_router stripping)
    and routes to:
      - on_ok: when query is new and non-empty
      - on_repeat: when query is empty or was already asked (normalized)

    YAML shape:
      - id: guard_repeat_query
        action: repeat_query_guard
        query_parser: JsonishQueryParser
        on_ok: search_auto
        on_repeat: suff_loop_guard
    """

    action_id = "repeat_query_guard"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        return {
            "payload_len": len((state.last_model_response or "") or ""),
            "asked_count": len(getattr(state, "retrieval_queries_asked", []) or []),
            "on_ok": raw.get("on_ok"),
            "on_repeat": raw.get("on_repeat"),
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
        on_ok = str(raw.get("on_ok") or "").strip()
        on_repeat = str(raw.get("on_repeat") or "").strip()
        if not on_ok:
            raise ValueError("repeat_query_guard: on_ok is required")
        if not on_repeat:
            raise ValueError("repeat_query_guard: on_repeat is required")

        payload = (state.last_model_response or "").strip()
        query, _warnings = _parse_payload(raw, payload)
        qn = _norm(query)
        if not qn:
            return on_repeat

        norm_set = getattr(state, "retrieval_queries_asked_norm", None)
        if not isinstance(norm_set, set):
            norm_set = set()
            state.retrieval_queries_asked_norm = norm_set

        if qn in norm_set:
            return on_repeat

        return on_ok

