from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


class ExpandDependencyTreeAction(PipelineActionBase):
    """
    Expands graph dependencies starting from retrieval seed nodes.

    Contract (as per our current decision):
    - expansion limits MUST be defined explicitly on this YAML step:
        - max_depth (int >= 1)
        - max_nodes (int >= 1)
        - edge_allowlist (list[str] or null)
    - no defaults, no guessing
    """

    @property
    def action_id(self) -> str:
        return "expand_dependency_tree"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        return {
            "seed_nodes_count": len(getattr(state, "retrieval_seed_nodes", None) or []),
            "max_depth": raw.get("max_depth", None),
            "max_nodes": raw.get("max_nodes", None),
            "edge_allowlist": raw.get("edge_allowlist", None),
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
            "expanded_nodes_count": len(getattr(state, "graph_expanded_nodes", None) or []),
            "graph_nodes_count": len(getattr(state, "graph_nodes", None) or []),
            "graph_edges_count": len(getattr(state, "graph_edges", None) or []),
            "graph_debug": dict(getattr(state, "graph_debug", None) or {}),
            "error": error,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw: Dict[str, Any] = step.raw or {}

        provider = getattr(runtime, "graph_provider", None)
        if provider is None:
            # Must be non-fatal (pipeline can run without graph)
            state.graph_debug = {"reason": "missing_graph_provider"}
            state.graph_expanded_nodes = []
            state.graph_nodes = []
            state.graph_edges = []
            return None

        seed_nodes: List[str] = list(getattr(state, "retrieval_seed_nodes", None) or [])
        if not seed_nodes:
            # Must be non-fatal: expansion is a no-op without seeds
            state.graph_debug = {"reason": "no_seeds"}
            state.graph_expanded_nodes = []
            state.graph_nodes = []
            state.graph_edges = []
            return None

        # ---- Contract: fail-fast on step config (NO DEFAULTS) ----
        if "max_depth" not in raw:
            raise ValueError("expand_dependency_tree: Missing required 'max_depth' in YAML step.")
        if "max_nodes" not in raw:
            raise ValueError("expand_dependency_tree: Missing required 'max_nodes' in YAML step.")
        if "edge_allowlist" not in raw:
            raise ValueError("expand_dependency_tree: Missing required 'edge_allowlist' in YAML step (can be null).")

        max_depth = int(raw.get("max_depth"))
        max_nodes = int(raw.get("max_nodes"))
        edge_allowlist = raw.get("edge_allowlist", None)
        if edge_allowlist is not None:
            edge_allowlist = list(edge_allowlist)

        if max_depth < 1:
            raise ValueError("expand_dependency_tree: 'max_depth' must be >= 1.")
        if max_nodes < 1:
            raise ValueError("expand_dependency_tree: 'max_nodes' must be >= 1.")

        settings = getattr(runtime, "pipeline_settings", None) or {}

        # Scope: branch is required, repository is strongly expected
        branch = (state.branch or settings.get("branch") or "").strip()
        if not branch:
            raise ValueError("expand_dependency_tree: state.branch is required by retrieval_contract")

        repository = (state.repository or settings.get("repository") or "").strip()
        if not repository:
            raise ValueError("expand_dependency_tree: Missing required 'repository' (state.repository or pipeline settings['repository']).")

        active_index = getattr(state, "active_index", None) or settings.get("active_index")

        retrieval_filters = dict(getattr(state, "retrieval_filters", None) or {})

        expand_fn = getattr(provider, "expand_dependency_tree", None)
        if expand_fn is None:
            state.graph_debug = {"reason": "graph_provider_missing_expand_dependency_tree"}
            state.graph_expanded_nodes = []
            state.graph_nodes = []
            state.graph_edges = []
            return None

        result = expand_fn(
            seed_nodes=seed_nodes,
            repository=repository,
            branch=branch,
            active_index=active_index,
            max_depth=max_depth,
            max_nodes=max_nodes,
            edge_allowlist=edge_allowlist,
            filters=retrieval_filters,
        ) or {}

        nodes = list(result.get("nodes", []) or [])
        edges = list(result.get("edges", []) or [])

        # Contract: expanded set is "seed + expanded nodes" (unique, keep order)
        expanded = []
        seen = set()
        for nid in list(seed_nodes) + list(nodes):
            s = str(nid)
            if s and s not in seen:
                seen.add(s)
                expanded.append(s)

        state.graph_seed_nodes = list(seed_nodes)
        state.graph_expanded_nodes = expanded
        state.graph_nodes = list(nodes)
        state.graph_edges = list(edges)

        state.graph_debug = {
            "reason": "ok",
            "seed_nodes_count": len(seed_nodes),
            "graph_nodes_count": len(nodes),
            "graph_edges_count": len(edges),
            "expanded_nodes_count": len(expanded),
        }

        return None
