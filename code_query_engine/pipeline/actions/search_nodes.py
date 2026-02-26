from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..providers.retrieval_backend_contract import SearchRequest
from ..query_parsers import BaseQueryParser, QueryParseResult, JsonishQueryParser
from ..state import PipelineState
from server.snapshots.snapshot_registry import SnapshotRegistry
from .base_action import PipelineActionBase

py_logger = logging.getLogger(__name__)

_ALLOWED_SEARCH_TYPES = {"semantic", "bm25", "hybrid"}
_ALLOWED_DATA_TYPES = {"regular_code", "db_code"}
_ALLOWED_SNAPSHOT_SOURCES = {"primary", "secondary"}
_ALLOWED_BM25_OPERATORS = {"and", "or"}

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
    IMPORTANT:
    - Do NOT clear context_blocks here.
    - context_blocks lifecycle is managed by manage_context_budget (within a run)
      and by creating a fresh PipelineState per new user turn.
    """
    state.retrieval_seed_nodes = []
    state.retrieval_hits = []
    state.graph_seed_nodes = []
    state.graph_expanded_nodes = []
    state.graph_edges = []
    state.graph_debug = {}
    state.graph_node_texts = []

    # Defensive: some older actions/tests may have this attribute dynamically
    if hasattr(state, "node_texts"):
        setattr(state, "node_texts", [])

def _norm_query_for_history(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def _resolve_snapshot_scope(
    settings: Dict[str, Any],
    state: PipelineState,
    step_raw: Dict[str, Any],
) -> Tuple[str, Optional[str], Optional[List[str]]]:
    source = str(step_raw.get("snapshot_source") or "primary").strip().lower()
    if not source:
        source = "primary"
    if source not in _ALLOWED_SNAPSHOT_SOURCES:
        raise ValueError(
            f"search_nodes: invalid snapshot_source='{source}'. "
            f"Allowed: {sorted(_ALLOWED_SNAPSHOT_SOURCES)}"
        )

    primary_id = (getattr(state, "snapshot_id", None) or settings.get("snapshot_id") or "").strip()
    secondary_id = (getattr(state, "snapshot_id_b", None) or settings.get("snapshot_id_b") or "").strip()

    if source == "primary":
        if not primary_id:
            raise ValueError("search_nodes: Missing required 'snapshot_id' for snapshot_source='primary'.")
        return primary_id, secondary_id or None, None

    if source == "secondary":
        if not secondary_id:
            raise ValueError("search_nodes: Missing required 'snapshot_id_b' for snapshot_source='secondary'.")
        return secondary_id, secondary_id, None

    return primary_id, secondary_id or None, None


def _merge_filters(
    *,
    settings: Dict[str, Any],
    state: PipelineState,
    step_raw: Dict[str, Any],
    repository: str,
    snapshot_id: str,
    snapshot_ids_any: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build the filter dict that MUST be applied at SEARCH TIME.

    IMPORTANT (retrieval_contract):
    - repository + branch are required (scope)
    - security filters from state.retrieval_filters are sacred
    - parsed/model payload must never override base filters
    """
    filters: Dict[str, Any] = {}
    filters.update(getattr(state, "retrieval_filters", None) or {})

    repo = (repository or "").strip()
    snapshot_id = (snapshot_id or "").strip()

    if not repo:
        raise ValueError("search_nodes: Missing required 'repository' (state.repository or pipeline settings['repository']).")
    if not snapshot_id:
        raise ValueError("search_nodes: Missing required 'snapshot_id' (state.snapshot_id or pipeline settings['snapshot_id']).")

    # Keep metadata keys compatible with existing unified-index layout
    filters["repo"] = repo
    if snapshot_ids_any:
        filters["snapshot_ids_any"] = [str(x).strip() for x in snapshot_ids_any if str(x).strip()]
    else:
        filters["snapshot_id"] = snapshot_id

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

    # Optional step-level narrowing filters.
    # ACL tags are OR semantics.
    acl_tags_any = step_raw.get("acl_tags_any")
    if isinstance(acl_tags_any, list) and acl_tags_any:
        clean_any = [s for s in _normalize_str_list(acl_tags_any)]
        existing_any = _normalize_str_list(filters.get("acl_tags_any"))
        filters["acl_tags_any"] = _normalize_str_list(existing_any + clean_any)

    # Classification labels are ALL/subset semantics.
    classification_labels_all = step_raw.get("classification_labels_all")
    if isinstance(classification_labels_all, list) and classification_labels_all:
        clean_labels = [s for s in _normalize_str_list(classification_labels_all)]
        existing_labels = _normalize_str_list(filters.get("classification_labels_all"))
        filters["classification_labels_all"] = _normalize_str_list(existing_labels + clean_labels)

    source_system_id = (step_raw.get("source_system_id") or "").strip()
    if source_system_id:
        filters["source_system_id"] = source_system_id

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

    # Normalize ACL filter aliases to acl_tags_any.
    if "permission_tags_all" in out and "acl_tags_any" not in out:
        out["acl_tags_any"] = out.get("permission_tags_all")
    if "permission_tags_any" in out and "acl_tags_any" not in out:
        out["acl_tags_any"] = out.get("permission_tags_any")

    if "acl_tags_any" in out:
        tags = out.get("acl_tags_any")
        if isinstance(tags, list):
            clean = _normalize_str_list(tags)
            if clean:
                out["acl_tags_any"] = clean
            else:
                out.pop("acl_tags_any", None)
        elif tags is None:
            out.pop("acl_tags_any", None)
        else:
            s = str(tags or "").strip()
            if s:
                out["acl_tags_any"] = [s]
            else:
                out.pop("acl_tags_any", None)

    if "classification_labels_all" in out:
        labels = out.get("classification_labels_all")
        if isinstance(labels, list):
            clean = _normalize_str_list(labels)
            if clean:
                out["classification_labels_all"] = clean
            else:
                out.pop("classification_labels_all", None)
        elif labels is None:
            out.pop("classification_labels_all", None)
        else:
            s = str(labels or "").strip()
            if s:
                out["classification_labels_all"] = [s]
            else:
                out.pop("classification_labels_all", None)

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


def _resolve_bm25_operator(
    *,
    search_type: str,
    payload_match_operator: str,
    parser_warnings: List[str],
    step_raw: Dict[str, Any],
    query: str,
) -> Optional[str]:
    _ = parser_warnings
    _ = step_raw
    _ = query
    if search_type != "bm25":
        return None

    if payload_match_operator in _ALLOWED_BM25_OPERATORS:
        return payload_match_operator

    return None


def _hit_id(hit: Any) -> str:
    """
    Support both hit objects (contract style) and dict hits (adapter style).
    """
    if isinstance(hit, dict):
        return str(hit.get("id") or hit.get("Id") or "").strip()
    return str(getattr(hit, "id", "") or "").strip()


def _hit_score(hit: Any) -> float:
    if isinstance(hit, dict):
        v = hit.get("score", 0.0)
    else:
        v = getattr(hit, "score", 0.0)
    try:
        return float(v)
    except Exception:
        return 0.0


def _hit_rank(hit: Any) -> int:
    if isinstance(hit, dict):
        v = hit.get("rank", 0)
    else:
        v = getattr(hit, "rank", 0)
    try:
        return int(v)
    except Exception:
        return 0


def _resolve_top_k(step_raw: Dict[str, Any], settings: Dict[str, Any]) -> int:
    """
    Contract:
    - step.raw.top_k is optional
    - pipeline_settings.top_k is optional
    - if both missing -> runtime error
    """
    top_k = _opt_int(step_raw.get("top_k"))
    if top_k is None:
        top_k = _opt_int(settings.get("top_k"))

    if top_k is None:
        raise ValueError("search_nodes: Missing required top_k (step.raw.top_k or pipeline_settings.top_k).")

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

    if mode == "codebert_rerank":
        raise ValueError("search_nodes: rerank='codebert_rerank' is reserved and not implemented yet.")

    if search_type != "semantic" and mode != "none":
        raise ValueError(f"search_nodes: rerank='{mode}' is only allowed for search_type='semantic' (contract).")

    return mode


def _log_security_abuse(reason: str, snapshot_set_id: str, snapshot_id: str) -> None:
    py_logger.warning(
        "[security_abuse] reason=%s snapshot_set_id=%s snapshot_id=%s",
        reason,
        snapshot_set_id,
        snapshot_id,
    )


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

        repo = (state.repository or settings.get("repository") or "").strip()
        snapshot_id_effective, _snapshot_id_b_effective, snapshot_ids_any = _resolve_snapshot_scope(settings, state, raw)
        base_filters = _merge_filters(
            settings=settings,
            state=state,
            step_raw=raw,
            repository=repo,
            snapshot_id=snapshot_id_effective,
            snapshot_ids_any=snapshot_ids_any,
        )
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
            "snapshot_source": str(raw.get("snapshot_source") or "primary").strip().lower() or "primary",
            "snapshot_id_effective": snapshot_id_effective,
            "snapshot_ids_any": snapshot_ids_any or [],
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
        search_type_cfg = str(raw.get("search_type") or "").strip().lower()
        allowed_cfg = sorted(list(_ALLOWED_SEARCH_TYPES | {"auto"}))
        if search_type_cfg not in (_ALLOWED_SEARCH_TYPES | {"auto"}):
            raise ValueError(f"search_nodes: invalid search_type='{search_type_cfg}'. Allowed: {allowed_cfg}")

        payload = (state.last_model_response or "").strip()
        parsed_query, parsed_filters, parse_warnings = ("", {}, [])
        if payload:
            parsed_query, parsed_filters, parse_warnings = _parse_payload_if_configured(raw, payload)

        parsed_filters = dict(parsed_filters or {})
        # Reserved parser-provided retrieval meta (not filters passed to backend)
        payload_search_type = str(parsed_filters.pop("__search_type", "") or "").strip().lower()
        payload_top_k = parsed_filters.pop("__top_k", None)
        payload_rrf_k = parsed_filters.pop("__rrf_k", None)
        payload_match_operator = str(parsed_filters.pop("__match_operator", "") or "").strip().lower()
        if payload_match_operator and payload_match_operator not in _ALLOWED_BM25_OPERATORS:
            payload_match_operator = ""

        # Resolve effective search_type if configured as auto.
        search_type = search_type_cfg
        if search_type_cfg == "auto":
            # 1) from payload (if provided)
            if payload_search_type:
                search_type = payload_search_type
            # 2) from prefix_router kind (state.last_prefix)
            if search_type == "auto":
                lp = str(getattr(state, "last_prefix", "") or "").strip().lower()
                if lp in ("semantic", "bm25", "hybrid"):
                    search_type = lp
            # 3) from step default (optional)
            if search_type == "auto":
                default_step = str(raw.get("default_search_type") or raw.get("default_search_method") or "").strip().lower()
                if default_step:
                    if default_step not in _ALLOWED_SEARCH_TYPES:
                        raise ValueError(
                            "search_nodes: invalid default_search_type/default_search_method="
                            f"'{default_step}'. Allowed: {sorted(_ALLOWED_SEARCH_TYPES)}"
                        )
                    search_type = default_step
            # 4) from pipeline settings default (optional)
            if search_type == "auto":
                # Keep backward-compatible alias (typo): default_serach_method
                default_pipe = str(
                    settings.get("default_search_method")
                    or settings.get("default_serach_method")
                    or ""
                ).strip().lower()
                if default_pipe:
                    if default_pipe not in _ALLOWED_SEARCH_TYPES:
                        raise ValueError(
                            "search_nodes: invalid pipeline.settings.default_search_method/default_serach_method="
                            f"'{default_pipe}'. Allowed: {sorted(_ALLOWED_SEARCH_TYPES)}"
                        )
                    search_type = default_pipe
            # 3) no explicit source -> fail fast (contract)
            if search_type == "auto":
                raise ValueError("search_nodes: requires explicit search_type when search_type='auto'.")

        if search_type not in _ALLOWED_SEARCH_TYPES:
            raise ValueError(f"search_nodes: resolved invalid search_type='{search_type}'. Allowed: {sorted(_ALLOWED_SEARCH_TYPES)}")
        state.search_type = search_type

        # Fail-fast validation of rerank mode (contract)
        state.rerank = _resolve_rerank(search_type, raw)

        query = (parsed_query or payload or "").strip()
        if not query:
            raise ValueError("search_nodes: Empty query after parsing/normalization is not allowed by retrieval_contract.")

        # Persist the effective query in state for downstream prompts (e.g., "do not repeat last query").
        state.retrieval_query = query
        state.retrieval_mode = search_type
        state.last_search_query = query
        state.last_search_type = search_type
        bm25_operator = _resolve_bm25_operator(
            search_type=search_type,
            payload_match_operator=payload_match_operator,
            parser_warnings=parse_warnings,
            step_raw=raw,
            query=query,
        )
        state.last_search_bm25_operator = bm25_operator

        # Record retrieval queries for this run (dedupe by normalized form).
        qn = _norm_query_for_history(query)
        if qn:
            norm_set = getattr(state, "retrieval_queries_asked_norm", None)
            if not isinstance(norm_set, set):
                norm_set = set()
                state.retrieval_queries_asked_norm = norm_set
            if qn not in norm_set:
                norm_set.add(qn)
                lst = getattr(state, "retrieval_queries_asked", None)
                if not isinstance(lst, list):
                    lst = []
                    state.retrieval_queries_asked = lst
                lst.append(query)

        repo = (state.repository or settings.get("repository") or "").strip()
        snapshot_id, snapshot_id_b_effective, snapshot_ids_any = _resolve_snapshot_scope(settings, state, raw)
        snapshot_set_id = (getattr(state, "snapshot_set_id", None) or settings.get("snapshot_set_id") or "").strip()

        if not repo:
            raise ValueError("search_nodes: Missing required 'repository' (state.repository or pipeline settings['repository']).")

        top_k = _resolve_top_k(raw, settings)
        original_top_k = int(top_k)

        # Optional: allow payload to reduce top_k (never increase) if explicitly enabled.
        allow_top_k_from_payload = bool(raw.get("allow_top_k_from_payload", False))
        if allow_top_k_from_payload:
            try:
                pt = _opt_int(payload_top_k)
            except Exception:
                pt = None
            if pt is not None and pt >= 1:
                top_k = min(int(original_top_k), int(pt))
                if top_k < 1:
                    top_k = 1

        base_filters = _merge_filters(
            settings=settings,
            state=state,
            step_raw=raw,
            repository=repo,
            snapshot_id=snapshot_id,
            snapshot_ids_any=snapshot_ids_any,
        )
        filters = dict(parsed_filters or {})
        filters.update(base_filters)
        filters = _normalize_and_validate_filters(filters)
        # Keep effective retrieval scope for downstream actions (e.g. fetch_node_texts).
        state.retrieval_filters = dict(filters)
        # Debug/traceability: remember what search actually used (including sacred filters).
        state.last_search_filters = dict(filters)

        backend = runtime.get_retrieval_backend()

        if snapshot_set_id and snapshot_id:
            client = getattr(backend, "_client", None)
            if client is not None:
                try:
                    registry = SnapshotRegistry(client)
                    allowed = registry.list_snapshots(snapshot_set_id=snapshot_set_id, repository=repo)
                    allowed_ids = {s.id for s in allowed}
                    if snapshot_id not in allowed_ids:
                        _log_security_abuse("snapshot_not_in_snapshot_set", snapshot_set_id, snapshot_id)
                        raise ValueError(
                            "search_nodes: snapshot_id is not allowed in snapshot_set_id (security abuse)."
                        )
                except Exception:
                    # If registry fails, bubble up as a clear error (fail-fast).
                    _log_security_abuse("snapshot_set_validation_failed", snapshot_set_id, snapshot_id)
                    raise

        if state.rerank != "none" and search_type == "semantic":
            widen_factor = settings.get("rerank_widen_factor", 6)
            try:
                widen_factor = int(widen_factor)
            except Exception:
                widen_factor = 6
            if widen_factor < 1:
                widen_factor = 1
            top_k = int(original_top_k * widen_factor)

        req = SearchRequest(
            search_type=search_type,  # type: ignore[arg-type]
            query=query,
            top_k=int(top_k),
            repository=repo,
            snapshot_id=snapshot_id,
            snapshot_set_id=snapshot_set_id or None,
            retrieval_filters=filters,
            rrf_k=(
                max(1, int(v))
                if (search_type == "hybrid" and raw.get("allow_rrf_k_from_payload", False) and (v := _opt_int(payload_rrf_k)) is not None)
                else None
            ),
            bm25_operator=bm25_operator,
        )

        resp = backend.search(req)

        # Contract outputs
        hits = list(resp.hits or [])
        if state.rerank != "none" and search_type == "semantic":
            hits = hits[:original_top_k]
        state.retrieval_seed_nodes = [hid for h in hits if (hid := _hit_id(h))]

        # A simple, stable debug form of hits (contract-friendly)
        state.retrieval_hits = [
            {
                "id": _hit_id(h),
                "score": _hit_score(h),
                "rank": _hit_rank(h),
            }
            for h in hits
            if _hit_id(h)
        ]

        try:
            results_for_history: List[Dict[str, Any]] = []
            for h in hits:
                hid = _hit_id(h)
                if not hid:
                    continue
                results_for_history.append({"Id": hid, "score": _hit_score(h), "rank": _hit_rank(h)})
            runtime.history_manager.add_iteration(query, results_for_history)
        except Exception:
            py_logger.exception("soft-failure: history_manager.add_iteration failed; continuing")

        return None
