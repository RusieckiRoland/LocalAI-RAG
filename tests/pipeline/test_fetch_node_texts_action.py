from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


class FakeGraphProvider:
    def __init__(self, *, node_texts: Optional[List[Dict[str, Any]]] = None) -> None:
        self._node_texts = list(node_texts or [])

    def fetch_node_texts(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return list(self._node_texts)


def test_fetch_node_texts_missing_graph_provider_sets_reason() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={"id": "fetch_texts", "action": "fetch_node_texts"},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch="develop", translate_chat=False)
    state.graph_expanded_nodes = ["A", "B"]

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "active_index": "nop_main_index"},
        graph_provider=None,
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.node_nexts == []
    assert state.graph_debug == {"reason": "missing_graph_provider"}


def test_fetch_node_texts_calls_provider_and_stores_result() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={
            "id": "fetch_texts",
            "action": "fetch_node_texts",
        },
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch="develop", translate_chat=False)
    state.graph_expanded_nodes = ["A", "B"]

    fake = FakeGraphProvider(node_texts=[{"id": "A", "text": "node A"}, {"id": "B", "text": "node B"}])

    rt = SimpleNamespace(
        pipeline_settings={
            "repository": "nopCommerce",
            "active_index": "nop_main_index",
            "max_context_tokens": 4096,
        },
        graph_provider=fake,
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    # Contract: action returns node_nexts with metadata fields.
    assert state.node_nexts == [
        {"id": "A", "text": "node A", "is_seed": False, "depth": 1, "parent_id": None},
        {"id": "B", "text": "node B", "is_seed": False, "depth": 1, "parent_id": None},
    ]
