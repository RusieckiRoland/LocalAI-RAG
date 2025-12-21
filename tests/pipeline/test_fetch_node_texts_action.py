from types import SimpleNamespace

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class FakeGraphProvider:
    def __init__(self):
        self.calls = []

    def fetch_node_texts(self, *, node_ids, repository=None, branch=None, active_index=None, max_chars=50_000):
        self.calls.append(
            {
                "node_ids": list(node_ids),
                "repository": repository,
                "branch": branch,
                "active_index": active_index,
                "max_chars": max_chars,
            }
        )
        return [{"id": nid, "text": f"text:{nid}"} for nid in node_ids]


def test_fetch_node_texts_requires_graph_provider():
    step = StepDef(id="fetch_texts", action="fetch_node_texts", raw={"id": "fetch_texts", "action": "fetch_node_texts"})
    state = PipelineState(user_query="q", session_id="s", consultant="c", branch="develop", translate_chat=False)
    state.graph_expanded_nodes = ["A"]

    rt = SimpleNamespace(pipeline_settings={}, graph_provider=None)
    FetchNodeTextsAction().execute(step, state, rt)

    assert getattr(state, "graph_debug", {})["reason"] == "missing_graph_provider"


def test_fetch_node_texts_calls_provider_and_stores_result():
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={
            "id": "fetch_texts",
            "action": "fetch_node_texts",
            "repository_from_settings": True,
            "active_index_from_settings": True,
        },
    )
    state = PipelineState(user_query="q", session_id="s", consultant="c", branch="develop", translate_chat=False)
    state.graph_expanded_nodes = ["A", "B"]

    fake = FakeGraphProvider()
    rt = SimpleNamespace(pipeline_settings={"repository": "nopCommerce", "active_index": "nop_main_index"}, graph_provider=fake)

    FetchNodeTextsAction().execute(step, state, rt)

    assert fake.calls
    call = fake.calls[0]
    assert call["node_ids"] == ["A", "B"]
    assert call["repository"] == "nopCommerce"
    assert call["active_index"] == "nop_main_index"
    assert call["branch"] == "develop"

    assert getattr(state, "graph_node_texts", None) == [{"id": "A", "text": "text:A"}, {"id": "B", "text": "text:B"}]
