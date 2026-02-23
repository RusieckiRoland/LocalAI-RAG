# code_query_engine/pipeline/actions/fetch_node_texts.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from classifiers.code_classifier import CodeKind, classify_text

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


def _normalize_language(kind: CodeKind) -> str:
    if kind == CodeKind.SQL:
        return "sql"
    if kind in (CodeKind.DOTNET, CodeKind.DOTNET_WITH_SQL):
        return "dotnet"
    return "unknown"


def _format_context_block(
    *,
    node_id: str,
    path: str,
    language: str,
    text: str,
    metadata_lines: Optional[List[str]] = None,
) -> str:
    nid = node_id or ""
    p = path or ""
    lang = language or "unknown"
    meta_lines = [str(x) for x in (metadata_lines or []) if str(x or "").strip()]
    return (
        "--- NODE ---\n"
        f"id: {nid}\n"
        f"path: {p}\n"
        f"language: {lang}\n"
        "compact: false\n"
        + ("metadata:\n" + "\n".join(meta_lines) + "\n" if meta_lines else "")
        + "text:\n"
        f"{text}\n"
    )


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

        fetch_nodes_fn = getattr(backend, "fetch_nodes", None)
        fetch_texts_fn = getattr(backend, "fetch_texts", None)
        if not callable(fetch_nodes_fn) and not callable(fetch_texts_fn):
            raise ValueError(
                "fetch_node_texts: retrieval_backend must provide fetch_texts(...) or fetch_nodes(...)."
            )

        settings = getattr(runtime, "pipeline_settings", None) or {}

        repository = (state.repository or settings.get("repository") or "").strip()
        if not repository:
            raise ValueError(
                "fetch_node_texts: Missing required 'repository' (state.repository or pipeline settings['repository'])."
            )

        retrieval_filters = dict(getattr(state, "retrieval_filters", None) or {})
        snapshot_id = str(
            retrieval_filters.get("snapshot_id")
            or getattr(state, "snapshot_id", None)
            or settings.get("snapshot_id")
            or ""
        ).strip()
        if not snapshot_id:
            raise ValueError("fetch_node_texts: Missing required 'snapshot_id' (state.snapshot_id or pipeline settings['snapshot_id']).")

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

        include_metadata = bool(raw.get("include_metadata_in_context", False))
        metadata_fields_raw = raw.get("metadata_fields", None)
        metadata_fields: Optional[list[str]] = None
        if metadata_fields_raw is not None:
            if isinstance(metadata_fields_raw, str):
                parts = [p.strip() for p in metadata_fields_raw.split(",")]
                metadata_fields = [p for p in parts if p]
            elif isinstance(metadata_fields_raw, list):
                metadata_fields = [str(x).strip() for x in metadata_fields_raw if str(x).strip()]
            else:
                raise ValueError("fetch_node_texts: metadata_fields must be a comma-separated string or list")

        # ---- Graph enrichment helpers ----
        edges = list(getattr(state, "graph_edges", None) or [])
        depth_map, parent_map = _build_depth_and_parent(seed_nodes=retrieval_seed_nodes, edges=edges)

        # ---- Strategy defines which IDs are considered and in what order ----
        # Allow dynamic override via inbox (message-based dispatcher).
        prioritization_mode_override: Optional[str] = None
        for msg in list(getattr(state, "inbox_last_consumed", None) or []):
            try:
                payload = (msg or {}).get("payload") or {}
                if not isinstance(payload, dict):
                    continue
                v = payload.get("prioritization_mode", payload.get("policy"))
                if v is None:
                    continue
                s = str(v or "").strip().lower()
                if s:
                    prioritization_mode_override = s
            except Exception:
                continue

        if prioritization_mode_override is not None:
            if prioritization_mode_override not in _ALLOWED_PRIORITIZATION_MODES:
                raise ValueError(
                    f"fetch_node_texts: invalid prioritization_mode='{prioritization_mode_override}' from inbox. "
                    f"Allowed: {sorted(_ALLOWED_PRIORITIZATION_MODES)}"
                )
            prioritization_mode = prioritization_mode_override
        else:
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
        id_to_node: Dict[str, Dict[str, Any]] = {}
        # Optional legacy shape from older backends (text-only). Kept for debug parity.
        id_to_text: Dict[str, str] = {}
        if callable(fetch_nodes_fn):
            raw_nodes = fetch_nodes_fn(
                node_ids=list(candidates_unique),
                repository=repository,
                snapshot_id=snapshot_id,
                retrieval_filters=retrieval_filters,
            ) or {}
            if not isinstance(raw_nodes, dict):
                raise ValueError("fetch_node_texts: retrieval_backend.fetch_nodes must return Dict[str, Dict] (contract).")
            for k, v in raw_nodes.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if not isinstance(v, dict):
                    continue
                id_to_node[k.strip()] = dict(v)
        else:
            id_to_text = fetch_texts_fn(  # type: ignore[misc]
                node_ids=list(candidates_unique),
                repository=repository,
                snapshot_id=snapshot_id,
                retrieval_filters=retrieval_filters,
            ) or {}
            if not isinstance(id_to_text, dict):
                raise ValueError("fetch_node_texts: retrieval_backend.fetch_texts must return Dict[str, str] (contract).")
            for k, v in id_to_text.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                id_to_node[k.strip()] = {"text": str(v or "")}

        seed_set = set(retrieval_seed_nodes)

        # ---- Budget enforcement (atomic snippets: skip, do not break) ----
        out: List[Dict[str, Any]] = []
        classification_union = set(getattr(state, "classification_labels_union", []) or [])
        acl_union = set(getattr(state, "acl_labels_union", []) or [])
        doc_level_max = getattr(state, "doc_level_max", None)
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
            node_props = id_to_node.get(node_id, None)

            # Backend returned NONE -> missing
            if node_props is None:
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

            # Aggregate permission-related metadata across retrieved chunks.
            cls_labels = (node_props or {}).get("classification_labels")
            if isinstance(cls_labels, list):
                for lbl in cls_labels:
                    s = str(lbl or "").strip()
                    if s:
                        classification_union.add(s)
            elif cls_labels is not None:
                s = str(cls_labels or "").strip()
                if s:
                    classification_union.add(s)

            acl_labels = (node_props or {}).get("acl_allow")
            if isinstance(acl_labels, list):
                for lbl in acl_labels:
                    s = str(lbl or "").strip()
                    if s:
                        acl_union.add(s)
            elif acl_labels is not None:
                s = str(acl_labels or "").strip()
                if s:
                    acl_union.add(s)

            doc_level_val = (node_props or {}).get("doc_level")
            try:
                if doc_level_val is not None:
                    dl = int(doc_level_val)
                    if doc_level_max is None or dl > doc_level_max:
                        doc_level_max = dl
            except Exception:
                pass

            text = str((node_props or {}).get("text") or "")

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

            meta_lines: list[str] = []
            if include_metadata:
                ignore_keys = {
                    "text",
                    "id",
                    "node_id",
                    "is_seed",
                    "depth",
                    "parent_id",
                }
                if metadata_fields:
                    keys = metadata_fields
                else:
                    keys = [k for k in (node_props or {}).keys() if k not in ignore_keys]
                for key in keys:
                    if not key or key in ignore_keys:
                        continue
                    val = (node_props or {}).get(key)
                    if val is None:
                        continue
                    if isinstance(val, list) or isinstance(val, set) or isinstance(val, tuple):
                        flat = [str(x).strip() for x in val if str(x).strip()]
                        if not flat:
                            continue
                        meta_lines.append(f"{key}: {', '.join(flat)}")
                    elif isinstance(val, dict):
                        try:
                            meta_lines.append(f"{key}: {json.dumps(val, ensure_ascii=False, separators=(',', ':'))}")
                        except Exception:
                            meta_lines.append(f"{key}: {str(val)}")
                    else:
                        s = str(val).strip()
                        if not s:
                            continue
                        meta_lines.append(f"{key}: {s}")

            # token budget gate (count full context block, not raw text)
            tok = 0
            if budget_tokens is not None:
                lang = _normalize_language(classify_text(str(text or "")).kind)
                path_for_budget = (
                    str((node_props or {}).get("path") or "")
                    or str((node_props or {}).get("repo_relative_path") or "")
                    or str((node_props or {}).get("source_file") or "")
                )
                block_text = _format_context_block(
                    node_id=str(node_id),
                    path=path_for_budget,
                    language=lang,
                    text=str(text or ""),
                    metadata_lines=meta_lines if meta_lines else None,
                )
                tok = _token_count(token_counter, block_text)
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
            item: Dict[str, Any] = {"id": node_id, "text": text}
            # Preserve useful metadata if backend provided it (for path attribution and debugging).
            for k in (
                "repo_relative_path",
                "source_file",
                "project_name",
                "class_name",
                "member_name",
                "symbol_type",
                "signature",
                "data_type",
                "file_type",
                "domain",
                "sql_kind",
                "sql_schema",
                "sql_name",
                "acl_allow",
                "classification_labels",
                "doc_level",
            ):
                v = (node_props or {}).get(k, None)
                if v is None:
                    continue
                item[k] = v

            item["is_seed"] = node_id in seed_set
            item["depth"] = int(depth_map.get(node_id, 1))
            item["parent_id"] = parent_map.get(node_id, None)

            if include_metadata:
                if meta_lines:
                    item["metadata_context"] = meta_lines
            out.append(item)

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
        state.classification_labels_union = sorted(classification_union)
        state.acl_labels_union = sorted(acl_union)
        state.doc_level_max = doc_level_max

        # ---- Update graph_debug ----
        debug = dict(getattr(state, "graph_debug", None) or {})
        debug.update(
            {
                "reason": "ok",
                "prioritization_mode": prioritization_mode,
                "prioritization_mode_source": ("inbox" if prioritization_mode_override is not None else "yaml"),
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
        returned_texts_count = len(id_to_text) if id_to_text else len(id_to_node)
        setattr(
            state,
            "_fetch_node_texts_debug",
            {
                "token_counter": token_strategy,
                "backend_fetch": {
                    "requested_ids_count": len(candidates_unique),
                    "requested_ids_preview": candidates_unique[:80],
                    "returned_nodes_count": len(id_to_node.keys()),
                    "returned_texts_count": returned_texts_count,
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
