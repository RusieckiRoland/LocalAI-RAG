from __future__ import annotations

from types import SimpleNamespace

from code_query_engine.pipeline.actions.expand_dependency_tree import ExpandDependencyTreeAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class FakeGraphProvider:
    def __init__(self) -> None:
        self.calls = []

    def expand_dependency_tree(
        self,
        *,
        seed_nodes,
        repository,
        branch,
        snapshot_id,
        max_depth,
        max_nodes,
        edge_allowlist,
        filters=None,
    ):
        self.calls.append(
            {
                "seed_nodes": list(seed_nodes or []),
                "repository": repository,
                "branch": branch,
                "snapshot_id": snapshot_id,
                "max_depth": max_depth,
                "max_nodes": max_nodes,
                "edge_allowlist": edge_allowlist,
                "filters": dict(filters or {}),
            }
        )
        return {"nodes": ["A", "B"], "edges": [{"from": "A", "to": "B", "type": "Calls"}]}


def test_expand_dependency_tree_calls_provider_and_updates_state() -> None:
    step = StepDef(
        id="expand",
        action="expand_dependency_tree",
        raw={
            "id": "expand",
            "action": "expand_dependency_tree",
            "max_depth_from_settings": "graph_max_depth",
            "max_nodes_from_settings": "graph_max_nodes",
            "edge_allowlist_from_settings": "graph_edge_allowlist",
        },
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.retrieval_seed_nodes = ["A"]

    fake = FakeGraphProvider()
    rt = SimpleNamespace(
        pipeline_settings={
            "repository": "nopCommerce",
            "snapshot_id": "snap",
            "graph_max_depth": 3,
            "graph_max_nodes": 10,
            "graph_edge_allowlist": ["Calls"],
        },
        graph_provider=fake,
    )

    ExpandDependencyTreeAction().execute(step, state, rt)

    assert state.graph_seed_nodes == ["A"]
    assert set(state.graph_expanded_nodes) == {"A", "B"}
    assert state.graph_edges
    assert state.graph_debug.get("reason") == "ok"
    assert fake.calls, "Provider should be called exactly once"
