# code_query_engine/pipeline/actions/search_nodes.py
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
    We reset retrieval/graph/text artifacts at the very beginning of search_nodes.
    """
    state.retrieval_seed_nodes = []
    state.graph_seed_nodes = []
    state.graph_expanded_nodes = []
    state.graph_edges = []
    state.graph_debug = {}
    state.graph_node_texts = []
    state.context_blocks = []

    # Defensive: some older actions/tests may have this attribute dynamically
    if hasattr(state, "node_nexts"):
        setattr(state, "node_nexts", [])


def _merge_filters(settings: Dict[str, Any], state: PipelineState, step_raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the filter dict that MUST be applied at SEARCH TIME.

    IMPORTANT (retrieval_contract):
    - repository + branch are required (scope)
    - ACL filters from state.retrieval_filters are sacred
    - parsed/model payload must never override base filters
    """
    filters: Dict[str, Any] = {}
    filters.update(state.retrieval_filters or {})

    repo = (state.repository or settings.get("repository") or "").strip()
    branch = (state.branch or settings.get("branch") or "").strip()

    if not repo:
        raise ValueError("search_nodes: Missing required 'repository' (state.repository or pipeline settings['repository']).")
    if not branch:
        raise ValueError("search_nodes: Missing required 'branch' (state.branch or pipeline settings['branch']).")

    # Keep metadata keys compatible with the existing unified-index layout
    # (retrievers historically use 'repo' not 'repository')
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
    Validate only the invariants we care about (today):
    - data_type (if present) must be one of: regular_code, db_code

    Do NOT rewrite arbitrary filter keys/values here.
    """
    out = dict(filters or {})

    if "data_type" in out:
        dt = out.get("data_type")
        # Accept scalar string only (router contract). If someone passes list -> fail loud.
        if isinstance(dt, list):
            raise ValueError("search_nodes: 'data_type' must be a single value (regular_code/db_code), not a list.")
        dt_s = str(dt or "").strip()
        if not dt_s:
            out.pop("data_type", None)
        else:
            if dt_s not in _ALLOWED_DATA_TYPES:
                raise ValueError(f"search_nodes: invalid data_type='{dt_s}'. Allowed: regular_code, db_code.")
            out["data_type"] = dt_s

    # permission_tags_all: must be a list of non-empty strings if present
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
            # tolerate a single string (be forgiving)
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


class SearchNodesAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "search_nodes"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        settings = runtime.pipeline_settings or {}
        raw = step.raw or {}

        search_type = str(raw.get("search_type") or "").strip().lower()
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

        # Contract: step.raw.top_k optional. Keep settings.top_k as a fallback for backward compatibility.
        top_k = _opt_int(raw.get("top_k"))
        if top_k is None:
            top_k = _opt_int(settings.get("top_k"))
        if top_k is None:
            top_k = 5

        effective_query = (parsed_query or payload or "").strip()

        return {
            "search_type": search_type,
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
        settings = runtime.pipeline_settings or {}
        raw = step.raw or {}

        payload = (state.last_model_response or "").strip()
        parsed_query, parsed_filters, warnings = _parse_payload_if_configured(raw, payload) if payload else ("", {}, [])

        base_filters = _merge_filters(settings, state, raw)
        effective_filters = dict(parsed_filters or {})
        effective_filters.update(base_filters)
        effective_filters = _normalize_and_validate_filters(effective_filters)

        effective_query = (parsed_query or payload or "").strip()

        return {
            "next_step_id": next_step_id,
            "search_type": getattr(state, "search_type", None),
            "query_effective": effective_query,
            "filters_effective": effective_filters,
            "parser_warnings": warnings,
            "retrieval_seed_nodes": list(getattr(state, "retrieval_seed_nodes", []) or []),
            "context_blocks_count": len(getattr(state, "context_blocks", []) or []),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}
        raw = step.raw or {}

        # Contract cleanup: must happen BEFORE doing anything else.
        _cleanup_retrieval_artifacts(state)

        # Contract: search_type MUST be defined explicitly on this search_nodes step (YAML).
               # Contract: search_type MUST be defined explicitly on this search_nodes step (YAML).
        search_type = str(raw.get("search_type") or "").strip().lower()
        if search_type not in _ALLOWED_SEARCH_TYPES:
            raise ValueError(f"search_nodes: invalid search_type='{search_type}'. Allowed: {sorted(_ALLOWED_SEARCH_TYPES)}")
        state.search_type = search_type

        # Contract: step.raw.rerank is optional, but allowed ONLY for search_type='semantic'.
        # Allowed values: none, keyword_rerank, codebert_rerank (reserved).
        rerank_raw = str(raw.get("rerank") or "").strip().lower()
        if not rerank_raw or rerank_raw == "none":
            rerank_raw = "none"

        allowed_reranks = {"none", "keyword_rerank", "codebert_rerank"}
        if rerank_raw not in allowed_reranks:
            raise ValueError(
                f"search_nodes: invalid rerank='{rerank_raw}'. Allowed: {sorted(allowed_reranks)}"
            )

        if rerank_raw != "none" and search_type != "semantic":
            raise ValueError(
                "search_nodes: rerank is allowed only for search_type='semantic' (retrieval_contract)."
            )

        if rerank_raw == "codebert_rerank":
            raise ValueError(
                "search_nodes: rerank='codebert_rerank' is reserved and not implemented yet."
            )


        # Payload is what HandlePrefix left us (prefix-stripped).
        payload = (state.last_model_response or "").strip()

        parsed_query, parsed_filters, _warnings = ("", {}, [])
        if payload:
            parsed_query, parsed_filters, _warnings = _parse_payload_if_configured(raw, payload)

        # Contract: query is derived ONLY from current payload (optionally parsed).
        query = (parsed_query or payload or "").strip()
        if not query:
            raise ValueError("search_nodes: Empty query after parsing/normalization is not allowed by retrieval_contract.")

        # Contract: repository + branch required (scope)
        repo = (state.repository or settings.get("repository") or "").strip()
        branch = (state.branch or settings.get("branch") or "").strip()
        if not repo:
            raise ValueError("search_nodes: Missing required 'repository' (state.repository or pipeline settings['repository']).")
        if not branch:
            raise ValueError("search_nodes: Missing required 'branch' (state.branch or pipeline settings['branch']).")

        # Contract: step.raw.top_k optional. Keep settings.top_k as a fallback for backward compatibility.
        top_k = _opt_int(raw.get("top_k"))
        if top_k is None:
            top_k = _opt_int(settings.get("top_k"))
        if top_k is None:
            top_k = 5

        # IMPORTANT: parsed filters can never override pipeline-enforced filters.
        base_filters = _merge_filters(settings, state, raw)
        filters = dict(parsed_filters or {})
        filters.update(base_filters)
        filters = _normalize_and_validate_filters(filters)

        active_index = getattr(state, "active_index", None) or settings.get("active_index")

        # ✅ Strict contract: use backend only (no direct FAISS/dispatcher access)
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

        # Contract output: ONLY IDs for graph expansion steps.
        state.retrieval_seed_nodes = [h.id for h in (resp.hits or []) if getattr(h, "id", None)]

        # History manager is a debug artifact; keep soft-failure behavior.
        try:
            # Keep a minimal structure similar to old "results" for debugging.
            results_for_history: List[Dict[str, Any]] = []
            for h in (resp.hits or []):
                results_for_history.append({"Id": h.id, "score": getattr(h, "score", 0.0), "rank": getattr(h, "rank", 0)})

            runtime.history_manager.add_iteration(query, results_for_history)
        except Exception:
            py_logger.exception("soft-failure: history_manager.add_iteration failed; continuing")

        return None
