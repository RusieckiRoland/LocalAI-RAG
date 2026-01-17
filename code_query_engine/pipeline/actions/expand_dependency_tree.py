from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase

py_logger = logging.getLogger(__name__)

 
class ExpandDependencyTreeAction(PipelineActionBase):
    """
    Expands a dependency graph starting from `state.retrieval_seed_nodes`.

    Provider contract (runtime.graph_provider):
      - expand_dependency_tree(seed_nodes=[...], max_depth=int, max_nodes=int, edge_allowlist=[...],
                              repository=str|None, branch=str|None, active_index=str|None)
        -> {"nodes": [...], "edges": [...]}
    """
    @property
    def action_id(self) -> str:
        return "expand_dependency_tree"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        settings = runtime.pipeline_settings or {}
        seed_nodes = list(getattr(state, "retrieval_seed_nodes", []) or [])

        def _read_int_setting(key: str, default: int) -> int:
            name = (raw.get(key) or "").strip()
            if not name:
                return default
            v = settings.get(name, default)
            try:
                return int(v)
            except Exception:
                py_logger.warning("Invalid int setting %s=%r; using default=%d", name, v, default, exc_info=True)
                return default

        def _read_list_setting(key: str) -> Optional[List[str]]:
            name = (raw.get(key) or "").strip()
            if not name:
                return None
            v = settings.get(name)
            return list(v) if isinstance(v, list) else None

        return {
            "seed_nodes": seed_nodes,
            "max_depth": _read_int_setting("max_depth_from_settings", 2),
            "max_nodes": _read_int_setting("max_nodes_from_settings", 200),
            "edge_allowlist": _read_list_setting("edge_allowlist_from_settings"),
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
            "graph_seed_nodes_count": len(getattr(state, "graph_seed_nodes", []) or []),
            "graph_expanded_nodes_count": len(getattr(state, "graph_expanded_nodes", []) or []),
            "graph_edges_count": len(getattr(state, "graph_edges", []) or []),
            "graph_debug": getattr(state, "graph_debug", None),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw: Dict[str, Any] = step.raw or {}
        settings: Dict[str, Any] = getattr(runtime, "pipeline_settings", None) or {}

        provider = getattr(runtime, "graph_provider", None)
        if provider is None:
            setattr(state, "graph_debug", {"reason": "missing_graph_provider"})
            return None

        def _extract_seed_nodes_from_results(results: Any) -> List[str]:
            # Deterministic: preserve first occurrence order
            if not isinstance(results, list):
                return []
            seen = set()
            out: List[str] = []
            for r in results:
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

        # Primary contract: seed nodes set by search_nodes
        seed_nodes: List[str] = list(getattr(state, "retrieval_seed_nodes", None) or [])

        # Fallbacks: be robust to minor refactors / different seed sources
        if not seed_nodes:
            seed_nodes = list(getattr(state, "graph_seed_nodes", None) or [])
        if not seed_nodes:
            seed_nodes = _extract_seed_nodes_from_results(getattr(state, "last_retrieval_results", None))

        if not seed_nodes:
            setattr(state, "graph_debug", {"reason": "no_seeds"})
            return None

        def _read_int_setting(key_name: str, default: int) -> int:
            key = (raw.get(key_name) or "").strip()
            if not key:
                return default
            if key not in settings:
                return default
            try:
                return int(settings[key])
            except Exception:
                py_logger.warning(
                    "Invalid int setting %s=%r; using default=%d",
                    key,
                    settings.get(key),
                    default,
                    exc_info=True,
                )
                return default

        def _read_list_setting(key_name: str) -> Optional[List[str]]:
            key = (raw.get(key_name) or "").strip()
            if not key:
                return None
            val = settings.get(key)
            if val is None:
                return None
            if isinstance(val, list):
                out = [str(x).strip() for x in val if str(x).strip()]
                return out or None
            if isinstance(val, str):
                out = [x.strip() for x in val.split(",") if x.strip()]
                return out or None
            return None

        max_depth = _read_int_setting("max_depth_from_settings", default=2)
        max_nodes = _read_int_setting("max_nodes_from_settings", default=200)
        edge_allowlist = _read_list_setting("edge_allowlist_from_settings")

        repository: Optional[str] = None
        # Default: pass repository unless step explicitly disables it.
        if raw.get("repository_from_settings") is not False:
            repository = settings.get("repository") or getattr(state, "repository", None) or None

        active_index: Optional[str] = None
        # Default: pass active_index unless step explicitly disables it.
       # Default: pass active_index unless step explicitly disables it.
        if raw.get("active_index_from_settings") is not False:
            active_index = (
                settings.get("active_index_id")
                or settings.get("active_index")
                or getattr(state, "active_index_id", None)
                or getattr(state, "active_index", None)
            )




        branch: Optional[str] = getattr(state, "branch", None) or (
            settings.get("branch") if isinstance(settings.get("branch"), str) else None
        )

        expand_fn = getattr(provider, "expand_dependency_tree", None) or getattr(provider, "expand", None)
        if expand_fn is None:
            setattr(state, "graph_debug", {"reason": "graph_provider_missing_expand"})
            return None

        out = expand_fn(
            seed_nodes=seed_nodes,
            max_depth=max_depth,
            max_nodes=max_nodes,
            edge_allowlist=edge_allowlist,
            repository=repository,
            branch=branch,
            active_index=active_index,
        ) or {}

        nodes = list(out.get("nodes") or [])
        edges = list(out.get("edges") or [])

        # Store results for next steps
        setattr(state, "graph_seed_nodes", list(seed_nodes))
        setattr(state, "graph_expanded_nodes", nodes)
        setattr(state, "graph_edges", edges)

        debug = dict(getattr(state, "graph_debug", None) or {})
        debug.update(
            {
                "seed_nodes_count": len(seed_nodes),
                "expanded_nodes_count": len(nodes),
                "edges_count": len(edges),
            }
        )
        setattr(state, "graph_debug", debug)

        return None
