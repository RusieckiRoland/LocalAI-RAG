# code_query_engine/pipeline/actions/fetch_node_texts.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


_ALLOWED_PRIORITIZATION_MODES = {"seed_first", "graph_first", "balanced"}


def _token_count(token_counter: Any, text: str) -> int:
    if token_counter is None:
        raise ValueError("fetch_node_texts: token_counter is required by retrieval_contract.")
    fn = getattr(token_counter, "count_tokens", None)
    if callable(fn):
        return int(fn(text))
    fn = getattr(token_counter, "count", None)
    if callable(fn):
        return int(fn(text))
    raise ValueError("fetch_node_texts: token_counter must provide count_tokens(...) or count(...).")


def _resolve_prioritization_mode(step_raw: Dict[str, Any]) -> str:
    """
    Contract:
    - step.raw.prioritization_mode is optional
    - allowed: seed_first | graph_first | balanced
    - missing/empty -> balanced
    - unknown -> runtime error (fail-fast)
    """
    raw_val = step_raw.get("prioritization_mode", None)
    if raw_val is None:
        mode = "balanced"
    else:
        mode = str(raw_val or "").strip().lower()
        if not mode:
            mode = "balanced"

    if mode not in _ALLOWED_PRIORITIZATION_MODES:
        raise ValueError(
            f"fetch_node_texts: invalid prioritization_mode='{mode}'. Allowed: {sorted(_ALLOWED_PRIORITIZATION_MODES)}"
        )

    return mode


def _build_depth_and_parent(
    *,
    seed_nodes: List[str],
    edges: List[Dict[str, Any]],
) -> Tuple[Dict[str, int], Dict[str, Optional[str]]]:
    """
    Compute BFS depths & parent pointers from edges.
    If graph is missing edges, depth defaults to 1, parent_id to None.
    """
    depth: Dict[str, int] = {}
    parent: Dict[str, Optional[str]] = {}

    if not edges:
        for s in seed_nodes:
            depth[s] = 0
            parent[s] = None
        return depth, parent


    adj: Dict[str, List[str]] = {}
    for e in edges:
        a = str(e.get("from_id") or "").strip()
        b = str(e.get("to_id") or "").strip()
        if not a or not b:
            raise ValueError("fetch_node_texts: graph_edges items must contain from_id/to_id (contract).")
        adj.setdefault(a, []).append(b)



    q: List[str] = []
    seen: Set[str] = set()

    for s in seed_nodes:
        seen.add(s)
        depth[s] = 0
        parent[s] = None
        q.append(s)


    while q:
        cur = q.pop(0)
        cur_d = depth.get(cur, 0)
        for nxt in adj.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            depth[nxt] = cur_d + 1
            parent[nxt] = cur
            q.append(nxt)

    return depth, parent


class FetchNodeTextsAction(PipelineActionBase):
    """
    Fetches text payloads for nodes from the graph provider.

    Contract (retrieval_contract.md):
    - input nodes: state.graph_expanded_nodes preferred, else state.graph_seed_nodes
    - branch + repository required
    - passes sacred filters: state.retrieval_filters
    - budget:
        - step.raw.budget_tokens OR
        - step.raw.budget_tokens_from_settings -> pipeline_settings[key] OR
        - fallback: pipeline_settings["max_context_tokens"] * 0.7 (required)
      token_counter is required for token enforcement
    - output: state.node_nexts list[dict] with fields:
        { id, text, is_seed, depth, parent_id }
    """

    @property
    def action_id(self) -> str:
        return "fetch_node_texts"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        node_ids = list(getattr(state, "graph_expanded_nodes", None) or getattr(state, "graph_seed_nodes", None) or [])
        return {
            "node_count": len(node_ids),
            "budget_tokens": raw.get("budget_tokens"),
            "budget_tokens_from_settings": raw.get("budget_tokens_from_settings"),
            "prioritization_mode": raw.get("prioritization_mode"),
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
        texts = list(getattr(state, "node_nexts", []) or [])
        return {
            "next_step_id": next_step_id,
            "node_texts_count": len(texts),
            "error": error,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}

        # Always ensure the attribute exists (contract)
        state.node_nexts = []

        provider = getattr(runtime, "graph_provider", None)
        if provider is None:
            state.graph_debug = {"reason": "missing_graph_provider"}
            state.node_nexts = []
            return None

        node_ids = list(getattr(state, "graph_expanded_nodes", None) or getattr(state, "graph_seed_nodes", None) or [])
        if not node_ids:
            state.graph_debug = {"reason": "no_nodes_for_fetch_node_texts"}
            state.node_nexts = []
            return None

        settings = getattr(runtime, "pipeline_settings", None) or {}

        branch = (state.branch or settings.get("branch") or "").strip()
        if not branch:
            raise ValueError("fetch_node_texts: state.branch is required by retrieval_contract")

        repository = (state.repository or settings.get("repository") or "").strip()
        if not repository:
            raise ValueError(
                "fetch_node_texts: Missing required 'repository' (state.repository or pipeline settings['repository'])."
            )

        active_index = getattr(state, "active_index", None) or settings.get("active_index")

        retrieval_filters = dict(getattr(state, "retrieval_filters", None) or {})

        fetch_fn = getattr(provider, "fetch_node_texts", None)
        if fetch_fn is None:
            state.graph_debug = {"reason": "graph_provider_missing_fetch_node_texts"}
            state.node_nexts = []
            return None

        # ---- Budget policy (contract) ----
        budget_tokens_raw = raw.get("budget_tokens", None)
        budget_tokens_from_settings = raw.get("budget_tokens_from_settings", None)
        max_chars_raw = raw.get("max_chars", None)
        max_context_tokens = settings.get("max_context_tokens", None)

        # Contract: max_chars is mutually exclusive with budget_tokens / budget_tokens_from_settings
        if max_chars_raw is not None and (budget_tokens_raw is not None or budget_tokens_from_settings is not None):
            raise ValueError("fetch_node_texts: max_chars cannot be used together with budget_tokens (contract).")

        max_chars: Optional[int] = None
        if max_chars_raw is not None:
            max_chars = int(max_chars_raw)
            if max_chars < 1:
                raise ValueError("fetch_node_texts: max_chars must be >= 1.")

        budget_tokens: Optional[int] = None

        if budget_tokens_raw is not None:
            budget_tokens = int(budget_tokens_raw)
            if budget_tokens < 1:
                raise ValueError("fetch_node_texts: budget_tokens must be >= 1.")
        elif budget_tokens_from_settings is not None:
            key = str(budget_tokens_from_settings or "").strip()
            if not key:
                raise ValueError("fetch_node_texts: budget_tokens_from_settings must be a non-empty string.")
            if key not in settings:
                raise ValueError(f"fetch_node_texts: pipeline_settings missing '{key}'.")
            budget_tokens = int(settings.get(key))
            if budget_tokens < 1:
                raise ValueError("fetch_node_texts: resolved budget_tokens must be >= 1.")
        else:
            if max_context_tokens is None:
                raise ValueError("fetch_node_texts: Missing required pipeline_settings['max_context_tokens'] (contract).")

            try:
                max_ctx = int(max_context_tokens)
            except Exception:
                raise ValueError("fetch_node_texts: pipeline_settings['max_context_tokens'] must be an integer (contract).")

            if max_ctx <= 0:
                raise ValueError("fetch_node_texts: pipeline_settings['max_context_tokens'] must be > 0 (contract).")

            budget_tokens = int(float(max_ctx) * 0.7)
            if budget_tokens <= 0:
                raise ValueError("fetch_node_texts: computed budget_tokens must be > 0 (contract).")

        token_counter = getattr(runtime, "token_counter", None)

        raw_texts = fetch_fn(
            node_ids=list(node_ids),
            repository=repository,
            branch=branch,
            active_index=active_index,
            filters=retrieval_filters,
        ) or []

        # Enrichment (contract format)
        seed_nodes = list(getattr(state, "graph_seed_nodes", None) or getattr(state, "retrieval_seed_nodes", None) or [])
        seed_set = set(seed_nodes)

        edges = list(getattr(state, "graph_edges", None) or [])
        depth_map, parent_map = _build_depth_and_parent(seed_nodes=seed_nodes, edges=edges)

        enriched: List[Dict[str, Any]] = []
        for it in raw_texts:
            node_id = str((it or {}).get("id") or (it or {}).get("Id") or "").strip()
            text = str((it or {}).get("text") or (it or {}).get("Text") or (it or {}).get("content") or "").strip()
            if not node_id:
                continue

            enriched.append(
                {
                    "id": node_id,
                    "text": text,
                    "is_seed": node_id in seed_set,
                    "depth": int(depth_map.get(node_id, 1)),
                    "parent_id": parent_map.get(node_id, None),
                }
            )

        # ---- Contract: prioritization_mode (deterministic ordering) ----
        prioritization_mode = _resolve_prioritization_mode(raw)

        def _safe_int(v: Any, default: int) -> int:
            try:
                return int(v)
            except Exception:
                return default

        if prioritization_mode == "seed_first":
            enriched.sort(
                key=lambda x: (
                    0 if bool(x.get("is_seed")) else 1,
                    _safe_int(x.get("depth"), 999999),
                    str(x.get("id") or ""),
                )
            )
        elif prioritization_mode == "graph_first":
            enriched.sort(
                key=lambda x: (
                    0 if not bool(x.get("is_seed")) else 1,
                    _safe_int(x.get("depth"), 999999),
                    str(x.get("id") or ""),
                )
            )
        else:
            # balanced
            enriched.sort(
                key=lambda x: (
                    _safe_int(x.get("depth"), 999999),
                    0 if bool(x.get("is_seed")) else 1,
                    str(x.get("id") or ""),
                )
            )

        # Enforce budget (contract)      
        if budget_tokens is not None:
            out: List[Dict[str, Any]] = []
            used = 0
            for it in enriched:
                t = it.get("text") or ""
                c = _token_count(token_counter, str(t))
                if used + c > budget_tokens:
                    # Atomic snippets: skip this candidate and continue checking next ones
                    continue
                out.append(it)
                used += c
            enriched = out


        state.node_nexts = list(enriched)

        debug = dict(getattr(state, "graph_debug", None) or {})
        debug.update({"node_texts_count": len(enriched), "reason": "ok"})
        state.graph_debug = debug

        return None
