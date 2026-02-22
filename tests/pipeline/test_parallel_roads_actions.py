from __future__ import annotations

import pytest

from code_query_engine.pipeline.actions.parallel_roads import ForkAction, MergeAction, ParallelRoadsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


def _runtime() -> PipelineRuntime:
    return PipelineRuntime(
        pipeline_settings={},
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=None,
        constants=None,
        retrieval_backend=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )


def _state() -> PipelineState:
    st = PipelineState(
        user_query="compare",
        session_id="s",
        consultant="shannon",
        snapshot_id="snap-a",
        snapshot_id_b="snap-b",
    )
    st.context_blocks = ["BASE_CONTEXT"]
    return st


def test_parallel_roads_action_initializes_state() -> None:
    state = _state()
    step = StepDef(id="parallel_roads", action="parallel_roads_action", raw={"id": "parallel_roads", "action": "parallel_roads_action"})

    next_step = ParallelRoadsAction().execute(step, state, _runtime())

    assert next_step is None
    assert isinstance(getattr(state, "parallel_roads", None), dict)


def test_fork_action_prepares_plan_and_jumps_to_search_step() -> None:
    state = _state()
    step = StepDef(
        id="fork_snapshots",
        action="fork_action",
        raw={
            "id": "fork_snapshots",
            "action": "fork_action",
            "search_action": "search_nodes",
            "snapshots": {
                "snapshot_a": "${snapshot_id}",
                "snapshot_b": "${snapshot_id_b}",
            },
        },
    )

    next_step = ForkAction().execute(step, state, _runtime())

    assert next_step == "search_nodes"
    assert state.snapshot_id == "snap-a"
    pr = state.parallel_roads
    assert pr["snapshots"] == [("snapshot_a", "snap-a"), ("snapshot_b", "snap-b")]
    assert pr["index"] == 0
    assert pr["current"] == {"name": "snapshot_a", "snapshot_id": "snap-a"}
    assert pr["fork_step_id"] == "fork_snapshots"


def test_fork_action_returns_on_done_after_last_snapshot() -> None:
    state = _state()
    state.parallel_roads = {
        "snapshots": [("snapshot_a", "snap-a"), ("snapshot_b", "snap-b")],
        "index": 2,
        "search_step_id": "search_nodes",
        "fork_step_id": "fork_snapshots",
        "results": {},
    }
    step = StepDef(
        id="fork_snapshots",
        action="fork_action",
        raw={
            "id": "fork_snapshots",
            "action": "fork_action",
            "search_action": "search_nodes",
            "snapshots": {"snapshot_a": "snap-a", "snapshot_b": "snap-b"},
            "on_done": "after_fork",
        },
    )

    next_step = ForkAction().execute(step, state, _runtime())

    assert next_step == "after_fork"


def test_merge_action_collects_snapshot_blocks_and_loops_back_to_fork() -> None:
    state = _state()
    state.snapshot_id = "snap-a"
    state.node_texts = [{"id": "N1", "path": "src/A.cs", "text": "class A {}"}]
    state.retrieval_seed_nodes = ["N1"]
    state.graph_seed_nodes = ["N1"]
    state.graph_expanded_nodes = ["N1"]
    state.graph_edges = [{"from": "N1", "to": "N2"}]
    state.graph_debug = {"reason": "ok"}
    state.parallel_roads = {
        "snapshots": [("snapshot_a", "snap-a"), ("snapshot_b", "snap-b")],
        "index": 0,
        "fork_step_id": "fork_snapshots",
        "original_snapshot_id": "orig-a",
        "original_snapshot_id_b": "orig-b",
        "results": {},
    }

    step = StepDef(
        id="merge_snapshots",
        action="merge_action",
        raw={
            "id": "merge_snapshots",
            "action": "merge_action",
            "snapshots": {"snapshot_a": "Branch {}", "snapshot_b": "Branch {}"},
            "on_done": "compare",
        },
    )

    next_step = MergeAction().execute(step, state, _runtime())

    assert next_step == "fork_snapshots"
    assert state.parallel_roads["index"] == 1
    first_blocks = state.parallel_roads["results"]["snapshot_a"]
    assert first_blocks[0] == "Branch snapshot_a"
    assert "--- NODE ---" in first_blocks[1]

    # Retrieval state must be cleared between fork iterations.
    assert state.node_texts == []
    assert state.retrieval_seed_nodes == []
    assert state.graph_seed_nodes == []
    assert state.graph_expanded_nodes == []
    assert state.graph_edges == []
    assert state.graph_debug == {}
    assert state.context_blocks == ["BASE_CONTEXT"]


def test_merge_action_finalizes_context_and_restores_original_snapshots() -> None:
    state = _state()
    state.snapshot_id = "snap-b"
    state.snapshot_friendly_names = {"snap-b": "Release 4.90"}
    state.node_texts = [{"id": "N2", "repo_relative_path": "src/B.cs", "text": "class B {}"}]
    state.parallel_roads = {
        "snapshots": [("snapshot_a", "snap-a"), ("snapshot_b", "snap-b")],
        "index": 1,
        "fork_step_id": "fork_snapshots",
        "original_snapshot_id": "orig-a",
        "original_snapshot_id_b": "orig-b",
        "results": {"snapshot_a": ["Branch snapshot_a", "--- NODE ---\nid: N1\npath: src/A.cs\ntext:\nclass A {}\n"]},
    }

    step = StepDef(
        id="merge_snapshots",
        action="merge_action",
        raw={
            "id": "merge_snapshots",
            "action": "merge_action",
            "snapshots": {"snapshot_a": "Branch {}", "snapshot_b": "Branch {}"},
            "on_done": "compare",
        },
    )

    next_step = MergeAction().execute(step, state, _runtime())

    assert next_step == "compare"
    assert state.snapshot_id == "orig-a"
    assert state.snapshot_id_b == "orig-b"

    merged = state.context_blocks
    assert merged[0] == "BASE_CONTEXT"
    assert "Branch snapshot_a" in merged
    assert "Branch Release 4.90" in merged


def test_merge_action_requires_initialized_parallel_roads() -> None:
    state = _state()
    step = StepDef(
        id="merge_snapshots",
        action="merge_action",
        raw={"id": "merge_snapshots", "action": "merge_action", "snapshots": {"snapshot_a": "Branch {}"}},
    )

    with pytest.raises(ValueError, match="missing parallel_roads state"):
        MergeAction().execute(step, state, _runtime())
