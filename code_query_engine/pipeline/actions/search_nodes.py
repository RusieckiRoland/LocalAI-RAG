from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..providers.retrieval_backend_contract import SearchRequest
from ..query_parsers import BaseQueryParser, QueryParseResult, JsonishQueryParser
from ..state import PipelineState
from .base_action import PipelineActionBase

py_logger = logging.getLogger(__name__)

_ALLOWED_SEARCH_TYPES = {"semantic", "bm25", "hybrid"}
_ALLOWED_DATA_TYPES = {"regular_code", "db_code"}

# "codebert_rerank" is for future use (contract allows it, execution can be backend-side later)
_ALLOWED_RERANK_MODES = {"none", "keyword_rerank", "codebert_rerank"}


def _normalize_str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            s = str(x or "").strip()
            if s:
                out.append(s)
        return out
    s = str(v or "").strip()
    return [s] if s else []


def _cleanup_retrieval_artifacts(state: PipelineState) -> None:
    """
    Contract-level cleanup to avoid cross-request state leakage.
    Reset retrieval/graph/text artifacts at the very beginning of search_nodes.
    """
    state.retrieval_seed_nodes = []
    state.retrieval_hits = []
    state.graph_seed_nodes = []
    state.graph_expanded_nodes = []
    state.graph_edges = []
    state.graph_debug = {}
    state.graph_node_texts = []
    state.context_blocks = []

    # Defensive: some older actions/tests may have this attribute dynamically
    if hasattr(state, "node_texts"):
        setattr(state, "node_texts", [])


def _merge_filters(settings: Dict[str, Any], state: PipelineState, step_raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the filter dict that MUST be applied at SEARCH TIME.

    IMPORTANT (retrieval_contract):
    - repository + branch are required (scope)
    - ACL filters from state.retrieval_filters are sacred
    - parsed/model payload must never override base filters
    """
    filters: Dict[str, Any] = {}
    filters.update(getattr(state, "retrieval_filters", None) or {})

    repo = (state.repository or settings.get("repository") or "").strip()
    branch = (state.branch or settings.get("branch") or "").strip()

    if not repo:
        raise ValueError("search_nodes: Missing required 'repository' (state.repository or pipeline settings['repository']).")
    if not branch:
        raise ValueError("search_nodes: Missing required 'branch' (state.branch or pipeline settings['branch']).")

    # Keep metadata keys compatible with existing unified-index layout
    filters["repo"] = repo
    filters["branch"] = branch

    # Optional multi-tenant / auth-ish filters from pipeline settings
    tenant_id = (settings.get("tenant_id") or "").strip()
    owner_id = (settings.get("owner_id") or "").strip()
    allowed_group_ids = settings.get("allowed_group_ids")

    if tenant_id:
        filters["tenant_id"] = tenant_id
    if owner_id:
        filters["owner_id"] = owner_id
    if isinstance(allowed_group_ids, list) and allowed_group_ids:
        filters["allowed_group_ids"] = [s for s in _normalize_str_list(allowed_group_ids)]

    # Step-level permission tags: require ALL tags
    perm_tags = step_raw.get("permission_tags_all")
    if isinstance(perm_tags, list) and perm_tags:
        filters["permission_tags_all"] = [s for s in _normalize_str_list(perm_tags)]

    return filters


def _resolve_parser(parser_name: str) -> BaseQueryParser:
    """
    Resolve parser instance by step.raw name.
    Supported:
    - "JsonishQueryParser" -> JsonishQueryParser()
    - "jsonish_v1" -> JsonishQueryParser() (by parser_id)
    """
    name = str(parser_name or "").strip()
    if not name:
        return JsonishQueryParser()

    if name == "JsonishQueryParser":
        return JsonishQueryParser()

    p = JsonishQueryParser()
    if name == p.parser_id:
        return p

    raise ValueError(f"Unknown query_parser '{name}'. Supported: JsonishQueryParser / jsonish_v1")


def _parse_payload_if_configured(step_raw: Dict[str, Any], payload: str) -> Tuple[str, Dict[str, Any], List[str]]:
    parser_name = str(step_raw.get("query_parser") or "").strip()
    if not parser_name:
        return payload.strip(), {}, []

    parser = _resolve_parser(parser_name)
    result: QueryParseResult = parser.parse(payload or "")
    query = (result.query or "").strip()
    filters = dict(result.filters or {})
    warnings = list(result.warnings or [])
    return query, filters, warnings


def _normalize_and_validate_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate only invariants we care about (today).
    Do NOT rewrite arbitrary filter keys/values here.
    """
    out = dict(filters or {})

    if "data_type" in out:
        dt = out.get("data_type")
        if isinstance(dt, list):
            raise ValueError("search_nodes: 'data_type' must be a single value (regular_code/db_code), not a list.")
        dt_s = str(dt or "").strip()
        if not dt_s:
            out.pop("data_type", None)
        else:
            if dt_s not in _ALLOWED_DATA_TYPES:
                raise ValueError(f"search_nodes: invalid data_type='{dt_s}'. Allowed: regular_code, db_code.")
            out["data_type"] = dt_s

    if "permission_tags_all" in out:
        tags = out.get("permission_tags_all")
        if isinstance(tags, list):
            clean = _normalize_str_list(tags)
            if clean:
                out["permission_tags_all"] = clean
            else:
                out.pop("permission_tags_all", None)
        elif tags is None:
            out.pop("permission_tags_all", None)
        else:
            s = str(tags or "").strip()
            if s:
                out["permission_tags_all"] = [s]
            else:
                out.pop("permission_tags_all", None)

    return out


def _opt_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    return int(s)


def _resolve_top_k(step_raw: Dict[str, Any], settings: Dict[str, Any]) -> int:
    """
    Contract:
    - step.raw.top_k is optional
    - pipeline_settings.top_k is optional
    - if both missing -> default to 5
    """
    top_k = _opt_int(step_raw.get("top_k"))
    if top_k is None:
        top_k = _opt_int(settings.get("top_k"))

    if top_k is None:
        top_k = 5

    if top_k < 1:
        raise ValueError("search_nodes: top_k must be >= 1.")

    return int(top_k)


def _resolve_rerank(search_type: str, step_raw: Dict[str, Any]) -> str:
    """
    Contract:
    - step.raw.rerank is optional
    - missing -> "none"
    - allowed: none | keyword_rerank | codebert_rerank
    - fail-fast:
        - unknown value -> runtime error
        - rerank != none when search_type != semantic -> runtime error
    """
    raw_val = step_raw.get("rerank", None)
    if raw_val is None:
        mode = "none"
    else:
        mode = str(raw_val or "").strip().lower()
        if not mode:
            mode = "none"

    if mode not in _ALLOWED_RERANK_MODES:
        raise ValueError(f"search_nodes: invalid rerank='{mode}'. Allowed: {sorted(_ALLOWED_RERANK_MODES)}")

    if search_type != "semantic" and mode != "none":
        raise ValueError(f"search_nodes: rerank='{mode}' is only allowed for search_type='semantic' (contract).")

    return mode


class SearchNodesAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "search_nodes"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        settings = runtime.pipeline_settings or {}
        raw = step.raw or {}

        payload = (state.last_model_response or "").strip()

        parsed_query = ""
        parsed_filters: Dict[str, Any] = {}
        warnings: List[str] = []
        if payload:
            parsed_query, parsed_filters, warnings = _parse_payload_if_configured(raw, payload)

        base_filters = _merge_filters(settings, state, raw)
        effective_filters = dict(parsed_filters or {})
        effective_filters.update(base_filters)
        effective_filters = _normalize_and_validate_filters(effective_filters)

        search_type = str(raw.get("search_type") or "").strip().lower()
        rerank = _resolve_rerank(search_type, raw)
        top_k = _resolve_top_k(raw, settings)
        effective_query = (parsed_query or payload or "").strip()

        return {
            "search_type": search_type,
            "rerank": rerank,
            "payload": payload,
            "query_parsed": (parsed_query or "").strip(),
            "query_effective": effective_query,
            "top_k": top_k,
            "filters_base": base_filters,
            "filters_parsed": parsed_filters,
            "filters_effective": effective_filters,
            "parser": raw.get("query_parser"),
            "parser_warnings": warnings,
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
            "search_type": getattr(state, "search_type", None),
            "rerank": getattr(state, "rerank", None),
            "retrieval_seed_nodes": list(getattr(state, "retrieval_seed_nodes", []) or []),
            "retrieval_hits_count": len(getattr(state, "retrieval_hits", []) or []),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}
        raw = step.raw or {}

        _cleanup_retrieval_artifacts(state)

        # search_type must be explicit in YAML
        search_type = str(raw.get("search_type") or "").strip().lower()
        if search_type not in _ALLOWED_SEARCH_TYPES:
            raise ValueError(f"search_nodes: invalid search_type='{search_type}'. Allowed: {sorted(_ALLOWED_SEARCH_TYPES)}")
        state.search_type = search_type

        # Fail-fast validation of rerank mode (contract)
        state.rerank = _resolve_rerank(search_type, raw)

        payload = (state.last_model_response or "").strip()
        parsed_query, parsed_filters, _warnings = ("", {}, [])
        if payload:
            parsed_query, parsed_filters, _warnings = _parse_payload_if_configured(raw, payload)

        query = (parsed_query or payload or "").strip()
        if not query:
            raise ValueError("search_nodes: Empty query after parsing/normalization is not allowed by retrieval_contract.")

        repo = (state.repository or settings.get("repository") or "").strip()
        branch = (state.branch or settings.get("branch") or "").strip()
        if not repo:
            raise ValueError("search_nodes: Missing required 'repository' (state.repository or pipeline settings['repository']).")
        if not branch:
            raise ValueError("search_nodes: Missing required 'branch' (state.branch or pipeline settings['branch']).")

        top_k = _resolve_top_k(raw, settings)

        base_filters = _merge_filters(settings, state, raw)
        filters = dict(parsed_filters or {})
        filters.update(base_filters)
        filters = _normalize_and_validate_filters(filters)

        active_index = getattr(state, "active_index", None) or settings.get("active_index")

        backend = runtime.get_retrieval_backend()

        req = SearchRequest(
            search_type=search_type,  # type: ignore[arg-type]
            query=query,
            top_k=int(top_k),
            repository=repo,
            branch=branch,
            retrieval_filters=filters,
            active_index=str(active_index).strip() if active_index else None,
        )

        resp = backend.search(req)

        # Contract outputs
        hits = list(resp.hits or [])
        state.retrieval_seed_nodes = [h.id for h in hits if getattr(h, "id", None)]

        # A simple, stable debug form of hits (contract-friendly)
        state.retrieval_hits = [
            {
                "id": h.id,
                "score": getattr(h, "score", 0.0),
                "rank": getattr(h, "rank", 0),
            }
            for h in hits
            if getattr(h, "id", None)
        ]

        try:
            results_for_history: List[Dict[str, Any]] = []
            for h in hits:
                results_for_history.append({"Id": h.id, "score": getattr(h, "score", 0.0), "rank": getattr(h, "rank", 0)})
            runtime.history_manager.add_iteration(query, results_for_history)
        except Exception:
            py_logger.exception("soft-failure: history_manager.add_iteration failed; continuing")

        return None
