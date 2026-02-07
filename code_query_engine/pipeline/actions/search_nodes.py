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
        snapshot_id, snapshot_id_b_effective, snapshot_ids_any = _resolve_snapshot_scope(settings, state, raw)
        snapshot_set_id = (getattr(state, "snapshot_set_id", None) or settings.get("snapshot_set_id") or "").strip()

        if not repo:
            raise ValueError("search_nodes: Missing required 'repository' (state.repository or pipeline settings['repository']).")

        top_k = _resolve_top_k(raw, settings)
        original_top_k = int(top_k)

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
