# code_query_engine/pipeline/actions/fetch_node_texts.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase

_ALLOWED_PRIORITIZATION_MODES = {"seed_first", "graph_first", "balanced"}


def _detect_token_counter_strategy(token_counter: Any) -> Dict[str, Any]:
    """
    Return a small, deterministic description of how token counting is performed.
    """
    if token_counter is None:
        return {
            "present": False,
            "strategy": None,
            "type": None,
        }

    fn_count_tokens = getattr(token_counter, "count_tokens", None)
    if callable(fn_count_tokens):
        return {
            "present": True,
            "strategy": "count_tokens(text)",
            "type": type(token_counter).__name__,
        }

    fn_count = getattr(token_counter, "count", None)
    if callable(fn_count):
        return {
            "present": True,
            "strategy": "count(text)",
            "type": type(token_counter).__name__,
        }

    return {
        "present": True,
        "strategy": "unknown (missing count_tokens/count)",
        "type": type(token_counter).__name__,
    }


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
    - depth=0 for seed nodes (contract)
    - depth>=1 for expanded graph nodes
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


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for x in items or []:
        s = str(x or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _build_strategy_order_ids(
    *,
    mode: str,
    seed_nodes: List[str],
    graph_nodes: List[str],
    depth_map: Dict[str, int],
    parent_map: Dict[str, Optional[str]],
) -> List[str]:
    """
    Build deterministic candidate ID order for each strategy.

    Inputs:
    - seed_nodes: retrieval seeds (ranking order from search_nodes)
    - graph_nodes: expanded nodes (may be empty if expand_dependency_tree was not used)

    Strategies:
    - seed_first:
        1) all seeds (in retrieval order)
        2) then all graph nodes (depth asc, id asc)
    - graph_first:
        For each seed in retrieval order:
        1) seed
        2) then all descendants belonging to this seed branch (depth asc, id asc)
    - balanced:
        Interleave seeds and graph nodes ~50/50 deterministically:
        - start with seed
        - then graph node
        - repeat
        Graph nodes ordered by depth asc first ("higher branches first").
    """
    seed_nodes = list(seed_nodes or [])
    graph_nodes = list(graph_nodes or [])
    seed_set = set(seed_nodes)

    # Graph candidates must not repeat seeds
    graph_only = [x for x in graph_nodes if x not in seed_set]

    # Deterministic ordering for graph nodes: shallower first, then id
    graph_sorted = sorted(
        graph_only,
        key=lambda node_id: (
            _safe_int(depth_map.get(node_id, 999999), 999999),
            str(node_id),
        ),
    )

    if mode == "seed_first":
        return list(seed_nodes) + list(graph_sorted)

    if mode == "graph_first":

        def _root_seed(node_id: str) -> Optional[str]:
            cur = node_id
            guard = 0
            while guard < 10000:
                guard += 1
                p = parent_map.get(cur, None)
                if p is None:
                    if cur in seed_set:
                        return cur
                    return None
                cur = p
            return None

        descendants: Dict[str, List[str]] = {s: [] for s in seed_nodes}

        for n in graph_sorted:
            r = _root_seed(n)
            if r is None:
                continue
            if r in descendants:
                descendants[r].append(n)

        ordered: List[str] = []
        for s in seed_nodes:
            ordered.append(s)
            ordered.extend(descendants.get(s, []))
        return ordered

    # balanced (default)
    out: List[str] = []
    si = 0
    gi = 0
    seeds = seed_nodes
    graphs = graph_sorted

    while si < len(seeds) or gi < len(graphs):
        if si < len(seeds):
            out.append(seeds[si])
            si += 1
        if gi < len(graphs):
            out.append(graphs[gi])
            gi += 1

    return out


class FetchNodeTextsAction(PipelineActionBase):
    """
    Fetches text payloads for nodes under token/char budget.

    IMPORTANT (contract alignment):
    - Text materialization MUST use runtime.retrieval_backend.fetch_texts(...)
      so backend can later be swapped (FAISS -> Weaviate) without touching the pipeline.
    - Graph provider is NOT used for text materialization here.

    NOTE:
    - fetch_texts(...) is called ONCE with all candidate IDs.
      Token/char budget is applied AFTER fetch, during materialization into state.node_texts.
    """

    @property
    def action_id(self) -> str:
        return "fetch_node_texts"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        raw = step.raw or {}
        seeds = list(getattr(state, "retrieval_seed_nodes", None) or [])
        graph_nodes = list(getattr(state, "graph_expanded_nodes", None) or [])
        return {
            "seed_count": len(seeds),
            "graph_expanded_count": len(graph_nodes),
            "budget_tokens": raw.get("budget_tokens"),
            "budget_tokens_from_settings": raw.get("budget_tokens_from_settings"),
            "max_chars": raw.get("max_chars"),
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
        texts = list(getattr(state, "node_texts", []) or [])

        # DEV logging: keep it readable and bounded
        max_items = 50
        max_text_chars = 4000

        bounded: List[Dict[str, Any]] = []
        for item in texts[:max_items]:
            if not isinstance(item, dict):
                continue
            raw_text = item.get("text")
            t = "" if raw_text is None else str(raw_text)
            text_len = len(t)

            if len(t) > max_text_chars:
                t = t[:max_text_chars] + f"\n... [truncated, len={text_len}]"

            bounded.append(
                {
                    "id": item.get("id"),
                    "is_seed": item.get("is_seed"),
                    "depth": item.get("depth"),
                    "parent_id": item.get("parent_id"),
                    "text_len": text_len,
                    "text_empty": (text_len == 0),
                    "text": t,
                }
            )

        debug = dict(getattr(state, "graph_debug", None) or {})
        materialization = dict(getattr(state, "_fetch_node_texts_debug", None) or {})

        return {
            "next_step_id": next_step_id,
            "node_texts_count": len(texts),
            "node_texts_logged_count": len(bounded),
            "node_texts": bounded,
            "graph_debug": debug,
            # NEW: explicit answer for "why do I have empty texts?"
            "materialization_debug": materialization,
            "error": error,
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}

        # Always ensure the attribute exists (contract)
        state.node_texts = []

        backend = getattr(runtime, "retrieval_backend", None)
        if backend is None:
            raise ValueError("fetch_node_texts: runtime.retrieval_backend is required by retrieval_contract.")

        fetch_texts_fn = getattr(backend, "fetch_texts", None)
        if not callable(fetch_texts_fn):
            raise ValueError("fetch_node_texts: runtime.retrieval_backend.fetch_texts(...) is required by retrieval_contract.")

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

        # ---- Inputs: seeds + optional graph expanded nodes ----
        retrieval_seed_nodes = _dedupe_preserve_order(list(getattr(state, "retrieval_seed_nodes", None) or []))
        graph_expanded_nodes = _dedupe_preserve_order(list(getattr(state, "graph_expanded_nodes", None) or []))

        if not retrieval_seed_nodes and not graph_expanded_nodes:
            state.graph_debug = {"reason": "no_nodes_for_fetch_node_texts"}
            state.node_texts = []
            setattr(state, "_fetch_node_texts_debug", {"reason": "no_nodes_for_fetch_node_texts"})
            return None

        # ---- Budget policy (contract) ----
        budget_tokens_raw = raw.get("budget_tokens", None)
        budget_tokens_from_settings = raw.get("budget_tokens_from_settings", None)
        max_chars_raw = raw.get("max_chars", None)
        max_context_tokens = settings.get("max_context_tokens", None)

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
        token_strategy = _detect_token_counter_strategy(token_counter)

        # ---- Graph enrichment helpers ----
        edges = list(getattr(state, "graph_edges", None) or [])
        depth_map, parent_map = _build_depth_and_parent(seed_nodes=retrieval_seed_nodes, edges=edges)

        # ---- Strategy defines which IDs are considered and in what order ----
        prioritization_mode = _resolve_prioritization_mode(raw)

        ordered_ids = _build_strategy_order_ids(
            mode=prioritization_mode,
            seed_nodes=retrieval_seed_nodes,
            graph_nodes=graph_expanded_nodes,
            depth_map=depth_map,
            parent_map=parent_map,
        )

        candidates_unique = _dedupe_preserve_order(list(ordered_ids))

        # ---- Materialize texts via backend interface ----
        id_to_text = fetch_texts_fn(
            node_ids=list(candidates_unique),
            repository=repository,
            branch=branch,
            retrieval_filters=retrieval_filters,
            active_index=active_index,
        ) or {}

        if not isinstance(id_to_text, dict):
            raise ValueError("fetch_node_texts: retrieval_backend.fetch_texts must return Dict[str, str] (contract).")

        seed_set = set(retrieval_seed_nodes)

        # ---- Budget enforcement (atomic snippets: skip, do not break) ----
        out: List[Dict[str, Any]] = []
        used_tokens = 0
        used_chars = 0

        skipped_due_budget = 0
        skipped_due_chars = 0

        missing_texts = 0
        empty_texts = 0

        first_skipped_due_budget_id: Optional[str] = None
        first_skipped_due_chars_id: Optional[str] = None
        first_missing_text_id: Optional[str] = None
        first_empty_text_id: Optional[str] = None

        missing_text_ids_preview: List[str] = []
        empty_text_ids_preview: List[str] = []

        first_included_id: Optional[str] = None
        last_included_id: Optional[str] = None

        decision_preview: List[Dict[str, Any]] = []
        decision_preview_limit = 80

        for node_id in ordered_ids:
            raw_text = id_to_text.get(node_id, None)

            # Backend returned NONE -> missing
            if raw_text is None:
                missing_texts += 1
                if first_missing_text_id is None:
                    first_missing_text_id = str(node_id)
                if len(missing_text_ids_preview) < 50:
                    missing_text_ids_preview.append(str(node_id))
                if len(decision_preview) < decision_preview_limit:
                    decision_preview.append(
                        {
                            "id": node_id,
                            "decision": "skip",
                            "reason": "missing_text_from_backend",
                        }
                    )
                continue

            text = str(raw_text)

            # Backend returned empty string -> empty
            if text == "":
                empty_texts += 1
                if first_empty_text_id is None:
                    first_empty_text_id = str(node_id)
                if len(empty_text_ids_preview) < 50:
                    empty_text_ids_preview.append(str(node_id))

            # max_chars gate
            if max_chars is not None:
                c_len = len(text)
                if used_chars + c_len > max_chars:
                    skipped_due_chars += 1
                    if first_skipped_due_chars_id is None:
                        first_skipped_due_chars_id = str(node_id)
                    if len(decision_preview) < decision_preview_limit:
                        decision_preview.append(
                            {
                                "id": node_id,
                                "decision": "skip",
                                "reason": "max_chars_budget",
                                "snippet_chars": c_len,
                                "used_chars_before": used_chars,
                                "max_chars": max_chars,
                            }
                        )
                    continue

            # token budget gate
            tok = _token_count(token_counter, text) if budget_tokens is not None else 0
            if budget_tokens is not None:
                if used_tokens + tok > budget_tokens:
                    skipped_due_budget += 1
                    if first_skipped_due_budget_id is None:
                        first_skipped_due_budget_id = str(node_id)
                    if len(decision_preview) < decision_preview_limit:
                        decision_preview.append(
                            {
                                "id": node_id,
                                "decision": "skip",
                                "reason": "token_budget",
                                "snippet_tokens": tok,
                                "used_tokens_before": used_tokens,
                                "budget_tokens": budget_tokens,
                            }
                        )
                    continue

            # include (even if empty -> you want to see it; the log will mark it)
            out.append(
                {
                    "id": node_id,
                    "text": text,
                    "is_seed": node_id in seed_set,
                    "depth": int(depth_map.get(node_id, 1)),
                    "parent_id": parent_map.get(node_id, None),
                }
            )

            if first_included_id is None:
                first_included_id = str(node_id)
            last_included_id = str(node_id)

            if len(decision_preview) < decision_preview_limit:
                decision_preview.append(
                    {
                        "id": node_id,
                        "decision": "include",
                        "snippet_tokens": tok if budget_tokens is not None else None,
                        "snippet_chars": len(text),
                        "text_empty": (len(text) == 0),
                        "used_tokens_after": (used_tokens + tok) if budget_tokens is not None else None,
                        "used_chars_after": (used_chars + len(text)) if max_chars is not None else None,
                    }
                )

            if max_chars is not None:
                used_chars += len(text)
            if budget_tokens is not None:
                used_tokens += tok

        state.node_texts = list(out)

        # ---- Update graph_debug ----
        debug = dict(getattr(state, "graph_debug", None) or {})
        debug.update(
            {
                "reason": "ok",
                "prioritization_mode": prioritization_mode,
                "seed_count": len(retrieval_seed_nodes),
                "graph_expanded_count": len(graph_expanded_nodes),
                "node_texts_count": len(out),
                "budget_tokens": budget_tokens,
                "used_tokens": used_tokens,
                "max_chars": max_chars,
                "used_chars": used_chars,
            }
        )
        state.graph_debug = debug

        # ---- Extra dev-only materialization diagnostics (bounded) ----
        setattr(
            state,
            "_fetch_node_texts_debug",
            {
                "token_counter": token_strategy,
                "backend_fetch": {
                    "requested_ids_count": len(candidates_unique),
                    "requested_ids_preview": candidates_unique[:80],
                    "returned_texts_count": len(id_to_text.keys()),
                    "missing_texts_count": missing_texts,
                    "first_missing_text_id": first_missing_text_id,
                    "missing_text_ids_preview": missing_text_ids_preview,
                    "empty_texts_count": empty_texts,
                    "first_empty_text_id": first_empty_text_id,
                    "empty_text_ids_preview": empty_text_ids_preview,
                },
                "budget": {
                    "budget_tokens": budget_tokens,
                    "used_tokens": used_tokens,
                    "budget_hit": skipped_due_budget > 0,
                    "skipped_due_budget_count": skipped_due_budget,
                    "first_skipped_due_budget_id": first_skipped_due_budget_id,
                },
                "chars_budget": {
                    "max_chars": max_chars,
                    "used_chars": used_chars,
                    "budget_hit": skipped_due_chars > 0,
                    "skipped_due_chars_count": skipped_due_chars,
                    "first_skipped_due_chars_id": first_skipped_due_chars_id,
                },
                "materialization": {
                    "first_included_id": first_included_id,
                    "last_included_id": last_included_id,
                    "decision_preview_count": len(decision_preview),
                    "decision_preview": decision_preview,
                },
            },
        )

        return None
