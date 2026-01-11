# code_query_engine/pipeline/actions/fetch_more_context.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..providers.retrieval import RetrievalDecision
from ..query_parsers import BaseQueryParser, QueryParseResult, JsonishQueryParser
from ..state import PipelineState
from .base_action import PipelineActionBase

py_logger = logging.getLogger(__name__)

_ALLOWED_SEARCH_TYPES = {"semantic", "bm25", "hybrid", "semantic_rerank"}
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


def _merge_filters(settings: Dict[str, Any], state: PipelineState, step_raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the filter dict that MUST be applied at SEARCH TIME.

    IMPORTANT:
    - unified-index metadata uses 'repo' (NOT 'repository')
    - branch is always required
    - pipeline-enforced filters (repo/branch/tenant/permissions) MUST NOT be overridden by model payload
    """
    filters: Dict[str, Any] = {}
    filters.update(state.retrieval_filters or {})

    repo = (state.repository or settings.get("repository") or "").strip()
    branch = (state.branch or settings.get("branch") or "").strip()

    if not branch:
        raise ValueError("Missing required 'branch' (state.branch or pipeline settings['branch']).")

    if repo:
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


def _normalize_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict):
            continue

        path = r.get("path") or r.get("File") or r.get("file") or ""
        content = r.get("content") or r.get("Content") or r.get("text") or ""
        start_line = r.get("start_line")
        end_line = r.get("end_line")

        normalized.append(
            {
                "path": path,
                "content": content,
                "start_line": start_line,
                "end_line": end_line,
                # Keep everything else for debugging / seed extraction.
                **{k: v for k, v in r.items() if k not in {"path", "file", "File", "content", "Content", "text"}},
            }
        )
    return normalized


def _extract_seed_nodes(results: List[Dict[str, Any]]) -> List[str]:
    seen = set()
    out: List[str] = []

    for r in results or []:
        if not isinstance(r, dict):
            continue

        nid = r.get("Id") or r.get("id") or r.get("node_id") or r.get("nodeId")
        if nid is None:
            continue

        v = str(nid).strip()
        if not v or v in seen:
            continue

        seen.add(v)
        out.append(v)

    return out


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
            raise ValueError("fetch_more_context: 'data_type' must be a single value (regular_code/db_code), not a list.")
        dt_s = str(dt or "").strip()
        if not dt_s:
            out.pop("data_type", None)
        else:
            if dt_s not in _ALLOWED_DATA_TYPES:
                raise ValueError(f"fetch_more_context: invalid data_type='{dt_s}'. Allowed: regular_code, db_code.")
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


class FetchMoreContextAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "fetch_more_context"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        settings = runtime.pipeline_settings or {}
        raw = step.raw or {}

        search_type = (getattr(state, "search_type", None) or getattr(state, "last_prefix", None) or "semantic")
        search_type = str(search_type or "").strip().lower()

        payload = (state.last_model_response or "").strip()

        parsed_query = ""
        parsed_filters: Dict[str, Any] = {}
        warnings: List[str] = []
        if payload:
            parsed_query, parsed_filters, warnings = _parse_payload_if_configured(raw, payload)

        # IMPORTANT: parsed filters can never override pipeline-enforced filters.
        base_filters = _merge_filters(settings, state, raw)
        effective_filters = dict(parsed_filters or {})
        effective_filters.update(base_filters)
        effective_filters = _normalize_and_validate_filters(effective_filters)

        top_k = int(settings.get("top_k", 12))
        effective_query = (parsed_query or state.retrieval_query or payload or "").strip()

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
        # Re-derive effective query/filters so traces always show what the search used.
        settings = runtime.pipeline_settings or {}
        raw = step.raw or {}

        payload = (state.last_model_response or "").strip()
        parsed_query, parsed_filters, warnings = _parse_payload_if_configured(raw, payload) if payload else ("", {}, [])

        base_filters = _merge_filters(settings, state, raw)
        effective_filters = dict(parsed_filters or {})
        effective_filters.update(base_filters)
        effective_filters = _normalize_and_validate_filters(effective_filters)

        effective_query = (parsed_query or state.retrieval_query or payload or "").strip()

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

        # Search type comes from PrefixRouterAction (state.last_prefix),
        # but we also persist it in state.search_type for telemetry/other steps.
        search_type = (getattr(state, "search_type", None) or getattr(state, "last_prefix", None) or "semantic")
        search_type = str(search_type or "").strip().lower()
        if search_type not in _ALLOWED_SEARCH_TYPES:
            raise ValueError(f"fetch_more_context: invalid search_type='{search_type}'. Allowed: {sorted(_ALLOWED_SEARCH_TYPES)}")
        state.search_type = search_type

        # Payload is what HandlePrefix left us (prefix-stripped).
        payload = (state.last_model_response or "").strip()

        parsed_query, parsed_filters, _warnings = ("", {}, [])
        if payload:
            parsed_query, parsed_filters, _warnings = _parse_payload_if_configured(raw, payload)

        # Query resolution: parser.query > state.retrieval_query > raw payload
        query = (parsed_query or state.retrieval_query or payload or "").strip()
        if not query:
            return None

        dispatcher = runtime.get_retrieval_dispatcher()
        if dispatcher is None:
            # Graceful: tests expect no throw in this case.
            return None

        top_k = int(settings.get("top_k", 12))

        # IMPORTANT: parsed filters can never override pipeline-enforced filters.
        base_filters = _merge_filters(settings, state, raw)
        filters = dict(parsed_filters or {})
        filters.update(base_filters)
        filters = _normalize_and_validate_filters(filters)

        decision = RetrievalDecision(mode=search_type, query=query)

        search_fn = getattr(dispatcher, "search", None)
        if callable(search_fn):
            results = search_fn(decision, top_k=top_k, settings=settings, filters=filters)
        else:
            # Fallback (older fakes)
            retriever = getattr(dispatcher, "retriever", None) or getattr(dispatcher, "_retriever", None)
            retr_search = getattr(retriever, "search", None) if retriever is not None else None
            if callable(retr_search):
                results = retr_search(query, top_k=top_k, filters=filters)
            else:
                results = []

        results = _normalize_results(results)

        # Seed nodes are used by graph expansion steps.
        state.retrieval_seed_nodes = _extract_seed_nodes(results)

        blocks: List[str] = []
        for r in results:
            path = (r.get("path") or "").strip()
            content = (r.get("content") or "").strip()
            if not content:
                continue

            start = r.get("start_line")
            end = r.get("end_line")

            header = f"### File: {path}" if path else "### File"
            if start is not None and end is not None:
                header += f" (lines {start}-{end})"

            blocks.append(f"{header}\n{content}".strip())

        if blocks:
            state.context_blocks.extend(blocks)

        try:
            runtime.history_manager.add_iteration(query, results)
        except Exception:
            py_logger.exception("soft-failure: history_manager.add_iteration failed; continuing")

        return None
