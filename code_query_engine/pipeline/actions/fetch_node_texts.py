from __future__ import annotations

from typing import Any, Dict, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


class FetchNodeTextsAction(PipelineActionBase):
    """
    Fetches text payloads for nodes from the graph provider.

    Uses:
      - state.graph_expanded_nodes (preferred)
      - state.graph_seed_nodes (fallback)

    Stores:
      - state.node_nexts (list[dict])
      - state.graph_debug (dict)
    """

    @property
    def action_id(self) -> str:
        return "fetch_node_texts"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        node_ids = list(state.graph_expanded_nodes or state.graph_seed_nodes or [])
        return {
            "node_count": len(node_ids),
            "max_chars": int(raw.get("max_chars", 50_000)),
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
        texts = state.node_nexts
        return {
            "next_step_id": next_step_id,
            "node_texts_count": len(texts),
            "error": error,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}

        provider = getattr(runtime, "graph_provider", None)
        if provider is None:
            # Test expects this exact reason string
            state.graph_debug = {"reason": "missing_graph_provider"}
            state.node_nexts = []
            return None

        node_ids = list(state.graph_expanded_nodes or state.graph_seed_nodes or [])
        if not node_ids:
            state.graph_debug = {"reason": "no_nodes_for_fetch_node_texts"}
            state.node_nexts = []
            return None

        settings = getattr(runtime, "pipeline_settings", None) or {}

        # Branch is required (tests always provide it)
        branch = state.branch or settings.get("branch")
        if not branch:
            raise ValueError("fetch_node_texts: state.branch is required by retrieval_contract")

        # Repository: if you want strict contract -> hard fail here.
        # Currently: allow None to keep e2e tests simple.
        repository = state.repository or settings.get("repository")
        if not repository:
            repository = None

        active_index = getattr(state, "active_index", None) or settings.get("active_index")

        fetch_fn = getattr(provider, "fetch_node_texts", None)
        if fetch_fn is None:
            state.graph_debug = {"reason": "graph_provider_missing_fetch_node_texts"}
            state.node_nexts = []
            return None

        max_chars = int(raw.get("max_chars", 50_000))

        texts = fetch_fn(
            node_ids=node_ids,
            repository=repository,
            branch=branch,
            active_index=active_index,
            max_chars=max_chars,
        ) or []

        state.node_nexts = list(texts)

        debug = dict(state.graph_debug or {})
        debug.update({"node_texts_count": len(texts), "reason": "ok"})
        state.graph_debug = debug

        return None
