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


class _RetrievalBackendStub:
    """Backend stub matching retrieval_contract: node_ids -> text mapping."""

    def __init__(self, graph_provider: Any) -> None:
        self._graph_provider = graph_provider

    def fetch_texts(
        self,
        *,
        node_ids: List[str],
        repository: str,
        snapshot_id: Optional[str],
        active_index: Optional[str],
        retrieval_filters: Dict[str, Any],
    ) -> Dict[str, str]:
        if self._graph_provider is None:
            return {}

        out = self._graph_provider.fetch_node_texts(
            node_ids=list(node_ids or []),
            repository=repository,
            snapshot_id=snapshot_id,
            active_index=active_index,
            filters=dict(retrieval_filters or {}),
        ) or []

        by_id = {str(x.get("id")): str(x.get("text") or "") for x in out if isinstance(x, dict)}
        return {nid: by_id[nid] for nid in node_ids if nid in by_id}


def test_fetch_node_texts_missing_graph_provider_sets_reason() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        # Use max_chars to avoid requiring runtime.token_counter in this unit test.
        raw={"id": "fetch_texts", "action": "fetch_node_texts", "max_chars": 100},
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.graph_expanded_nodes = ["A", "B"]

    rt = SimpleNamespace(
        pipeline_settings={"repository": "nopCommerce", "active_index": "nop_main_index", "max_context_tokens": 4096},
        graph_provider=None,
        retrieval_backend=_RetrievalBackendStub(None),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    assert state.node_texts == []
    assert state.graph_debug.get("reason") == "ok"
    assert state.graph_debug.get("node_texts_count") == 0


def test_fetch_node_texts_calls_provider_and_stores_result() -> None:
    step = StepDef(
        id="fetch_texts",
        action="fetch_node_texts",
        raw={
            "id": "fetch_texts",
            "action": "fetch_node_texts",
        },
    )

    state = PipelineState(user_query="q", session_id="s", consultant="c", branch=None, translate_chat=False, snapshot_id="snap")
    state.graph_expanded_nodes = ["A", "B"]

    fake = FakeGraphProvider(node_texts=[{"id": "A", "text": "node A"}, {"id": "B", "text": "node B"}])

    rt = SimpleNamespace(
        pipeline_settings={
            "repository": "nopCommerce",
            "active_index": "nop_main_index",
            "max_context_tokens": 4096,
        },
        graph_provider=fake,
        retrieval_backend=_RetrievalBackendStub(fake),
        token_counter=SimpleNamespace(count_tokens=lambda s: len(str(s).split())),
    )

    FetchNodeTextsAction().execute(step, state, rt)

    # Contract: action returns node_texts with metadata fields.
    assert state.node_texts == [
        {"id": "A", "text": "node A", "is_seed": False, "depth": 1, "parent_id": None},
        {"id": "B", "text": "node B", "is_seed": False, "depth": 1, "parent_id": None},
    ]
