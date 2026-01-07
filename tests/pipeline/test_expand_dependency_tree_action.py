from types import SimpleNamespace

from code_query_engine.pipeline.actions.expand_dependency_tree import ExpandDependencyTreeAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class FakeGraphProvider:
    def __init__(self):
        self.calls = []

    def expand_dependency_tree(
        self,
        *,
        seed_nodes,
        max_depth=2,
        max_nodes=200,
        edge_allowlist=None,
        repository=None,
        branch=None,
        active_index=None,
    ):
        self.calls.append(
            {
                "seed_nodes": list(seed_nodes),
                "max_depth": max_depth,
                "max_nodes": max_nodes,
                "edge_allowlist": edge_allowlist,
                "repository": repository,
                "branch": branch,
                "active_index": active_index,
            }
        )
        return {"nodes": ["A", "B"], "edges": [{"from": "A", "to": "B", "type": "Calls"}]}


def test_expand_dependency_tree_no_graph_provider_sets_debug():
    step = StepDef(id="expand", action="expand_dependency_tree", raw={"id": "expand", "action": "expand_dependency_tree"})
    state = PipelineState(user_query="q", session_id="s", consultant="c", branch="develop", translate_chat=False)
    state.retrieval_seed_nodes = ["A"]

    rt = SimpleNamespace(pipeline_settings={}, graph_provider=None)

    ExpandDependencyTreeAction().execute(step, state, rt)

    assert getattr(state, "graph_debug", {})["reason"] == "missing_graph_provider"


def test_expand_dependency_tree_no_seeds_is_noop():
    step = StepDef(id="expand", action="expand_dependency_tree", raw={"id": "expand", "action": "expand_dependency_tree"})
    state = PipelineState(user_query="q", session_id="s", consultant="c", branch="develop", translate_chat=False)
    state.retrieval_seed_nodes = []

    rt = SimpleNamespace(pipeline_settings={}, graph_provider=FakeGraphProvider())

    ExpandDependencyTreeAction().execute(step, state, rt)

    assert getattr(state, "graph_debug", {})["reason"] == "no_seeds"


def test_expand_dependency_tree_calls_provider_and_updates_state():
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

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch="develop", translate_chat=False)
    state.retrieval_seed_nodes = ["A"]

    fake = FakeGraphProvider()
    rt = SimpleNamespace(
        pipeline_settings={
            "repository": "nopCommerce",
            "active_index": "nop_main_index",
            "graph_max_depth": 3,
            "graph_max_nodes": 10,
            "graph_edge_allowlist": ["Calls"],
        },
        graph_provider=fake,
    )

    ExpandDependencyTreeAction().execute(step, state, rt)

    assert fake.calls, "Graph provider should be called"
    call = fake.calls[0]
    assert call["seed_nodes"] == ["A"]
    assert call["max_depth"] == 3
    assert call["max_nodes"] == 10
    assert call["edge_allowlist"] == ["Calls"]
    assert call["repository"] == "nopCommerce"
    assert call["active_index"] == "nop_main_index"
    assert call["branch"] == "develop"

    assert getattr(state, "graph_seed_nodes", None) == ["A"]
    assert getattr(state, "graph_expanded_nodes", None) == ["A", "B"]
    assert getattr(state, "graph_edges", None) == [{"from": "A", "to": "B", "type": "Calls"}]
