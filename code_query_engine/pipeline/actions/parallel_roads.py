# code_query_engine/pipeline/actions/parallel_roads.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..state import PipelineState
from .base_action import PipelineActionBase


def _resolve_snapshot_ref(raw_val: str, state: PipelineState) -> str:
    v = str(raw_val or "").strip()
    if v in ("${snapshot_id}", "$snapshot_id", "snapshot_id"):
        sid = str(getattr(state, "snapshot_id", None) or "").strip()
        if not sid:
            raise ValueError("parallel_roads: snapshot_id is required but missing in state")
        return sid
    if v in ("${snapshot_id_b}", "$snapshot_id_b", "snapshot_id_b"):
        sid = str(getattr(state, "snapshot_id_b", None) or "").strip()
        if not sid:
            raise ValueError("parallel_roads: snapshot_id_b is required but missing in state")
        return sid
    return v


def _normalize_snapshots(raw: Any, state: PipelineState) -> List[Tuple[str, str]]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("parallel_roads: snapshots must be a non-empty mapping")
    out: List[Tuple[str, str]] = []
    for k, v in raw.items():
        name = str(k or "").strip()
        sid = _resolve_snapshot_ref(str(v or ""), state)
        if not name or not sid:
            raise ValueError("parallel_roads: snapshot keys and values must be non-empty strings")
        out.append((name, sid))
    return out


def _render_label(template: str, name: str) -> str:
    t = str(template or "").strip()
    if not t:
        return name
    if "{}" in t:
        return t.replace("{}", name)
    if "{name}" in t:
        try:
            return t.format(name=name)
        except Exception:
            return f"{t} {name}"
    return f"{t} {name}"


def _display_snapshot_name(*, state: PipelineState, snapshot_id: str, fallback: str) -> str:
    mapping = getattr(state, "snapshot_friendly_names", None) or {}
    if isinstance(mapping, dict):
        label = str(mapping.get(snapshot_id) or "").strip()
        if label:
            return label
    return fallback


def _node_block(node: Dict[str, Any]) -> str:
    node_id = str(node.get("node_id") or node.get("id") or "").strip()
    path = str(
        node.get("path")
        or node.get("repo_relative_path")
        or node.get("source_file")
        or node.get("source")
        or ""
    ).strip()
    text = str(node.get("text") or "")
    return (
        "--- NODE ---\n"
        f"id: {node_id}\n"
        f"path: {path}\n"
        "text:\n"
        f"{text}\n"
    )


def _clear_retrieval(state: PipelineState) -> None:
    state.retrieval_seed_nodes = []
    state.retrieval_hits = []
    state.graph_seed_nodes = []
    state.graph_expanded_nodes = []
    state.graph_edges = []
    state.graph_debug = {}
    state.graph_node_texts = []
    state.node_texts = []


class ParallelRoadsAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "parallel_roads_action"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        return {
            "has_parallel_roads_state": bool(getattr(state, "parallel_roads", None)),
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
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # Optional initializer hook (no-op by default).
        if not hasattr(state, "parallel_roads"):
            setattr(state, "parallel_roads", {})
        return None


class ForkAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "fork_action"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        pr = getattr(state, "parallel_roads", {}) or {}
        return {
            "snapshots_count": len(pr.get("snapshots", []) or []),
            "index": int(pr.get("index", 0) or 0),
            "search_step_id": pr.get("search_step_id"),
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
        pr = getattr(state, "parallel_roads", {}) or {}
        cur = pr.get("current", None) or {}
        return {
            "next_step_id": next_step_id,
            "current_snapshot_name": cur.get("name"),
            "current_snapshot_id": cur.get("snapshot_id"),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        snapshots = _normalize_snapshots(raw.get("snapshots"), state)
        search_step_id = str(raw.get("search_action") or "").strip()
        if not search_step_id:
            raise ValueError("fork_action: search_action is required (step id of search_nodes)")

        pr = getattr(state, "parallel_roads", None)
        if not isinstance(pr, dict) or not pr:
            pr = {
                "snapshots": snapshots,
                "index": 0,
                "search_step_id": search_step_id,
                "fork_step_id": step.id,
                "original_snapshot_id": getattr(state, "snapshot_id", None),
                "original_snapshot_id_b": getattr(state, "snapshot_id_b", None),
                "results": {},
            }
            setattr(state, "parallel_roads", pr)
        else:
            pr.setdefault("snapshots", snapshots)
            pr.setdefault("search_step_id", search_step_id)
            pr.setdefault("fork_step_id", step.id)

        idx = int(pr.get("index", 0) or 0)
        plan = list(pr.get("snapshots", []) or [])
        if idx >= len(plan):
            return raw.get("on_done")

        name, snapshot_id = plan[idx]
        pr["current"] = {"name": name, "snapshot_id": snapshot_id}

        state.snapshot_id = snapshot_id
        return search_step_id


class MergeAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "merge_action"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        pr = getattr(state, "parallel_roads", {}) or {}
        return {
            "snapshots_count": len(pr.get("snapshots", []) or []),
            "index": int(pr.get("index", 0) or 0),
            "node_texts_count": len(getattr(state, "node_texts", []) or []),
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
        pr = getattr(state, "parallel_roads", {}) or {}
        return {
            "next_step_id": next_step_id,
            "results_keys": sorted(list((pr.get("results", {}) or {}).keys())),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        pr = getattr(state, "parallel_roads", None)
        if not isinstance(pr, dict) or not pr:
            raise ValueError("merge_action: missing parallel_roads state (fork_action must run first)")

        raw = step.raw or {}
        labels_raw = raw.get("snapshots")
        if not isinstance(labels_raw, dict) or not labels_raw:
            raise ValueError("merge_action: snapshots mapping is required (label templates by snapshot name)")

        plan = list(pr.get("snapshots", []) or [])
        idx = int(pr.get("index", 0) or 0)
        if idx >= len(plan):
            return raw.get("on_done")

        name, snapshot_id = plan[idx]
        display_name = _display_snapshot_name(state=state, snapshot_id=snapshot_id, fallback=name)
        label = _render_label(str(labels_raw.get(name) or ""), display_name)

        nodes = list(getattr(state, "node_texts", []) or [])
        blocks = [label]
        for n in nodes:
            if isinstance(n, dict):
                blocks.append(_node_block(n))

        results = pr.get("results")
        if not isinstance(results, dict):
            results = {}
        results[name] = blocks
        pr["results"] = results

        _clear_retrieval(state)

        pr["index"] = idx + 1
        if pr["index"] < len(plan):
            fork_step_id = str(pr.get("fork_step_id") or "").strip()
            if not fork_step_id:
                raise ValueError("merge_action: fork_step_id missing in parallel_roads state")
            return fork_step_id

        combined: List[str] = []
        for snap_name, _ in plan:
            combined.extend(results.get(snap_name, []))

        if combined:
            state.context_blocks = list(getattr(state, "context_blocks", []) or []) + combined

        state.snapshot_id = pr.get("original_snapshot_id")
        state.snapshot_id_b = pr.get("original_snapshot_id_b")

        return raw.get("on_done")
