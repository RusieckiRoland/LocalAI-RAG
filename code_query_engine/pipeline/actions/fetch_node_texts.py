from __future__ import annotations

from typing import Any, Dict, List, Optional

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

    Stores the result on:
      - state.graph_node_texts

    Provider contract (runtime.graph_provider):
      - fetch_node_texts(node_ids=[...], repository=str|None, branch=str|None, active_index=str|None)
        -> [{"id": "...", "text": "..."}, ...]
    """

    @property
    def action_id(self) -> str:
        return "fetch_node_texts"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        node_ids = list(getattr(state, "graph_expanded_nodes", None) or getattr(state, "graph_seed_nodes", []) or [])
        max_chars = int(raw.get("max_chars", 50_000))
        return {
            "node_ids": node_ids,
            "node_count": len(node_ids),
            "max_chars": max_chars,
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
        texts = getattr(state, "graph_node_texts", None)
        return {
            "next_step_id": next_step_id,
            "node_texts_count": len(texts or []) if isinstance(texts, list) else None,
            "graph_debug": getattr(state, "graph_debug", None),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw: Dict[str, Any] = step.raw or {}
        settings: Dict[str, Any] = getattr(runtime, "pipeline_settings", None) or {}

        provider = getattr(runtime, "graph_provider", None)
        if provider is None:
            setattr(state, "graph_debug", {"reason": "missing_graph_provider"})
            return None

        node_ids: List[str] = list(getattr(state, "graph_expanded_nodes", None) or [])
        if not node_ids:
            node_ids = list(getattr(state, "graph_seed_nodes", None) or [])
        if not node_ids:
            setattr(state, "graph_debug", {"reason": "no_nodes"})
            setattr(state, "graph_node_texts", [])
            return None

        repository: Optional[str] = settings.get("repository") or getattr(state, "repository", None) or None
        active_index: Optional[str] = (
            settings.get("active_index")
            or settings.get("index")
            or getattr(state, "active_index", None)
            or None
        )

        # If repository is missing we still *try* to fetch (test harnesses/providers may not require it).
        # If the provider rejects repository=None, we soft-fail below.
        if not repository:
            debug = dict(getattr(state, "graph_debug", None) or {})
            debug.update({"reason": "missing_repository_for_fetch_node_texts"})
            setattr(state, "graph_debug", debug)


        branch: Optional[str] = getattr(state, "branch", None) or (
            settings.get("branch") if isinstance(settings.get("branch"), str) else None
        )
        if not branch:
            setattr(state, "graph_debug", {"reason": "missing_branch_for_fetch_node_texts"})
            setattr(state, "graph_node_texts", [])
            return None

        fetch_fn = getattr(provider, "fetch_node_texts", None)
        if fetch_fn is None:
            setattr(state, "graph_debug", {"reason": "graph_provider_missing_fetch_node_texts"})
            setattr(state, "graph_node_texts", [])
            return None

        max_chars = int(raw.get("max_chars", 50_000))

        try:
            texts = fetch_fn(
                node_ids=node_ids,
                repository=repository,
                branch=branch,
                active_index=active_index,
                max_chars=max_chars,
            ) or []
        except Exception as ex:
            debug = dict(getattr(state, "graph_debug", None) or {})
            debug.update(
                {
                    "reason": "fetch_node_texts_failed",
                    "error_type": ex.__class__.__name__,
                    "error": str(ex)[:200],
                }
            )
            setattr(state, "graph_debug", debug)
            setattr(state, "graph_node_texts", [])
            return None


        setattr(state, "graph_node_texts", list(texts))

        debug = dict(getattr(state, "graph_debug", None) or {})
        debug.update({"node_texts_count": len(texts)})
        setattr(state, "graph_debug", debug)

        return None
