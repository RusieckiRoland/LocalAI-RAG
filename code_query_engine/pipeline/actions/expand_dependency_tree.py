# code_query_engine/pipeline/actions/expand_dependency_tree.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


def _normalize_graph_edges(edges: List[Any]) -> List[Dict[str, str]]:
    """
    Contract:
    Each graph_edges item MUST be:
      { "from_id": str, "to_id": str, "edge_type": str }

    Provider may return:
      - already normalized: from_id/to_id/edge_type
      - legacy-ish: from/to/(type)
    We normalize deterministically and fail-fast if the edge is malformed.
    """
    out: List[Dict[str, str]] = []

    for e in (edges or []):
        if not isinstance(e, dict):
            raise ValueError("expand_dependency_tree: graph_edges item must be a dict (contract).")

        from_id = str(e.get("from_id") or e.get("from") or "").strip()
        to_id = str(e.get("to_id") or e.get("to") or "").strip()
        edge_type = str(e.get("edge_type") or e.get("type") or "").strip()

        if not from_id or not to_id:
            raise ValueError("expand_dependency_tree: graph_edges item missing from_id/to_id (contract).")

        if not edge_type:
            # edge_type is required by contract; if provider doesn't supply it yet,
            # use a deterministic placeholder instead of silently emitting empty string.
            edge_type = "unknown"

        out.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "edge_type": edge_type,
            }
        )

    return out


def _set_graph_debug(
    state: PipelineState,
    *,
    reason: str,
    seed_count: int,
    expanded_count: int,
    edges_count: int,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Contract-friendly, stable debug schema:
      - reason
      - seed_count
      - expanded_count
      - edges_count
    """
    dbg: Dict[str, Any] = {
        "reason": str(reason or "").strip() or "unknown",
        "seed_count": int(seed_count),
        "expanded_count": int(expanded_count),
        "edges_count": int(edges_count),
    }
    if extra:
        dbg.update(dict(extra))
    state.graph_debug = dbg


def _count_edge_types(edges: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in edges or []:
        if not isinstance(e, dict):
            continue
        t = str(e.get("edge_type") or "unknown").strip() or "unknown"
        counts[t] = counts.get(t, 0) + 1
    return counts


class ExpandDependencyTreeAction(PipelineActionBase):
    """
    Expands graph dependencies for retrieval seed nodes.

    Contract (retrieval_contract.md):
    - seed_nodes come from state.retrieval_seed_nodes
    - branch + repository required
    - max_depth/max_nodes/edge_allowlist must be resolved via *_from_settings keys
    - ACL filters from state.retrieval_filters are sacred and must be passed through
    """

    @property
    def action_id(self) -> str:
        return "expand_dependency_tree"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        settings = getattr(runtime, "pipeline_settings", None) or {}

        seed_nodes = list(getattr(state, "retrieval_seed_nodes", None) or [])
        return {
            "seed_count": len(seed_nodes),
            "max_depth_from_settings": raw.get("max_depth_from_settings"),
            "max_nodes_from_settings": raw.get("max_nodes_from_settings"),
            "edge_allowlist_from_settings": raw.get("edge_allowlist_from_settings"),
            "settings_keys_present": {
                "repository": bool((state.repository or settings.get("repository"))),
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
        # DEV logging: keep bounded but explicit.
        seed_nodes = list(getattr(state, "graph_seed_nodes", []) or [])
        expanded_nodes = list(getattr(state, "graph_expanded_nodes", []) or [])
        edges = list(getattr(state, "graph_edges", []) or [])

        max_seed_nodes = 200
        max_expanded_nodes = 400
        max_edges_preview = 300

        seed_preview = seed_nodes[:max_seed_nodes]
        expanded_preview = expanded_nodes[:max_expanded_nodes]

        edges_preview: List[Dict[str, Any]] = []
        for e in edges[:max_edges_preview]:
            if not isinstance(e, dict):
                continue
            edges_preview.append(
                {
                    "from_id": e.get("from_id"),
                    "to_id": e.get("to_id"),
                    "edge_type": e.get("edge_type"),
                }
            )

        edge_type_counts = _count_edge_types(edges)

        return {
            "next_step_id": next_step_id,
            "seed_count": len(seed_nodes),
            "expanded_count": len(expanded_nodes),
            "edges_count": len(edges),
            "graph_debug": dict(getattr(state, "graph_debug", {}) or {}),
            # === NEW: concrete graph output ===
            "graph_seed_nodes_logged_count": len(seed_preview),
            "graph_seed_nodes": seed_preview,
            "graph_expanded_nodes_logged_count": len(expanded_preview),
            "graph_expanded_nodes": expanded_preview,
            "graph_edges_logged_count": len(edges_preview),
            "graph_edges_preview": edges_preview,
            "graph_edge_type_counts": edge_type_counts,
            "error": error,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw: Dict[str, Any] = step.raw or {}
        settings = getattr(runtime, "pipeline_settings", None) or {}

        provider = getattr(runtime, "graph_provider", None)
        if provider is None:
            # non-fatal
            _set_graph_debug(state, reason="missing_graph_provider", seed_count=0, expanded_count=0, edges_count=0)
            state.graph_seed_nodes = []
            state.graph_expanded_nodes = []
            state.graph_nodes = []
            state.graph_edges = []
            return None

        seed_nodes: List[str] = list(getattr(state, "retrieval_seed_nodes", None) or [])
        if not seed_nodes:
            # non-fatal
            _set_graph_debug(state, reason="no_seeds", seed_count=0, expanded_count=0, edges_count=0)
            state.graph_seed_nodes = []
            state.graph_expanded_nodes = []
            state.graph_nodes = []
            state.graph_edges = []
            return None

        # ---- Contract: required YAML keys (no defaults) ----
        if "max_depth_from_settings" not in raw:
            raise ValueError("expand_dependency_tree: Missing required 'max_depth_from_settings' in YAML step.")
        if "max_nodes_from_settings" not in raw:
            raise ValueError("expand_dependency_tree: Missing required 'max_nodes_from_settings' in YAML step.")
        if "edge_allowlist_from_settings" not in raw:
            raise ValueError(
                "expand_dependency_tree: Missing required 'edge_allowlist_from_settings' in YAML step (can be null)."
            )

        max_depth_key = str(raw.get("max_depth_from_settings") or "").strip()
        max_nodes_key = str(raw.get("max_nodes_from_settings") or "").strip()
        edge_allowlist_key = str(raw.get("edge_allowlist_from_settings") or "").strip()

        if not max_depth_key:
            raise ValueError("expand_dependency_tree: max_depth_from_settings must be a non-empty string.")
        if not max_nodes_key:
            raise ValueError("expand_dependency_tree: max_nodes_from_settings must be a non-empty string.")
        if not edge_allowlist_key:
            raise ValueError(
                "expand_dependency_tree: edge_allowlist_from_settings must be a non-empty string (can point to null)."
            )

        if max_depth_key not in settings:
            raise ValueError(f"expand_dependency_tree: pipeline_settings missing '{max_depth_key}'.")
        if max_nodes_key not in settings:
            raise ValueError(f"expand_dependency_tree: pipeline_settings missing '{max_nodes_key}'.")
        if edge_allowlist_key not in settings:
            raise ValueError(f"expand_dependency_tree: pipeline_settings missing '{edge_allowlist_key}' (can be null).")

        max_depth = int(settings.get(max_depth_key))
        max_nodes = int(settings.get(max_nodes_key))

        edge_allowlist = settings.get(edge_allowlist_key)
        if edge_allowlist is not None:
            if not isinstance(edge_allowlist, list):
                raise ValueError("expand_dependency_tree: edge_allowlist must be a list or null.")
            edge_allowlist = list(edge_allowlist)

        if max_depth < 1:
            raise ValueError("expand_dependency_tree: resolved max_depth must be >= 1.")
        if max_nodes < 1:
            raise ValueError("expand_dependency_tree: resolved max_nodes must be >= 1.")

        repository = (state.repository or settings.get("repository") or "").strip()
        if not repository:
            raise ValueError(
                "expand_dependency_tree: Missing required 'repository' (state.repository or pipeline settings['repository'])."
            )

        snapshot_id = (
            getattr(state, "snapshot_id", None)
            or settings.get("snapshot_id")
            or getattr(state, "active_index", None)
            or settings.get("active_index")
            or ""
        ).strip()
        if not snapshot_id:
            raise ValueError("expand_dependency_tree: Missing required 'snapshot_id' (state.snapshot_id or pipeline settings['snapshot_id']).")

        active_index = getattr(state, "active_index", None) or settings.get("active_index")

        # Sacred ACL filters
        retrieval_filters = dict(getattr(state, "retrieval_filters", None) or {})

        expand_fn = getattr(provider, "expand_dependency_tree", None)
        if expand_fn is None:
            # non-fatal
            _set_graph_debug(
                state,
                reason="graph_provider_missing_expand_dependency_tree",
                seed_count=len(seed_nodes),
                expanded_count=0,
                edges_count=0,
            )
            state.graph_seed_nodes = list(seed_nodes)
            state.graph_expanded_nodes = []
            state.graph_nodes = []
            state.graph_edges = []
            return None

        result = (
            expand_fn(
                seed_nodes=list(seed_nodes),
                repository=repository,
                branch=None,
                active_index=active_index,
                snapshot_id=snapshot_id,
                max_depth=max_depth,
                max_nodes=max_nodes,
                edge_allowlist=edge_allowlist,
                filters=retrieval_filters,
            )
            or {}
        )

        nodes = list(result.get("nodes") or [])
        edges_raw = list(result.get("edges") or [])
        edges = _normalize_graph_edges(edges_raw)

        # Optional ACL filter hook (provider-defined).
        filter_fn = getattr(provider, "filter_by_permissions", None)
        if callable(filter_fn):
            allowed_nodes = list(
                filter_fn(
                    node_ids=list(nodes),
                    retrieval_filters=retrieval_filters,
                    repository=repository,
                    branch=None,
                    snapshot_id=snapshot_id,
                    active_index=active_index,
                )
                or []
            )
            allowed_set = set(allowed_nodes)
            nodes = [n for n in nodes if n in allowed_set]
            edges = [e for e in edges if e.get("from_id") in allowed_set and e.get("to_id") in allowed_set]

        state.graph_seed_nodes = list(seed_nodes)
        state.graph_expanded_nodes = list(nodes)
        state.graph_nodes = list(nodes)
        state.graph_edges = list(edges)

        # Contract debug keys (always stable)
        _set_graph_debug(
            state,
            reason="ok",
            seed_count=len(seed_nodes),
            expanded_count=len(nodes),
            edges_count=len(edges),
        )

        return None
