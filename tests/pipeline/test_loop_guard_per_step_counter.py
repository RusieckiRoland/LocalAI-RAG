from types import SimpleNamespace

import pytest

from code_query_engine.pipeline.actions.loop_guard import LoopGuardAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


class _RT(PipelineRuntime):
    def __init__(self, *, max_turn_loops: int) -> None:
        super().__init__(
            pipeline_settings={"max_turn_loops": max_turn_loops},
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
            add_plant_link=None,
        )


def _state() -> PipelineState:
    return PipelineState(
        user_query="q",
        session_id="s",
        consultant="c",
        branch=None,
        translate_chat=False,
        snapshot_id="snap",
    )


def test_loop_guard_counts_per_step_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PIPELINE_TRACE", "1")
    rt = _RT(max_turn_loops=2)
    setattr(rt, "pipeline_trace_enabled", True)

    state = _state()

    s1 = StepDef(id="lg1", action="loop_guard", raw={"on_allow": "A", "on_deny": "D"})
    s2 = StepDef(id="lg2", action="loop_guard", raw={"on_allow": "A", "on_deny": "D"})

    act = LoopGuardAction()

    assert act.execute(s1, state, rt) == "A"
    assert act.execute(s1, state, rt) == "A"
    assert act.execute(s1, state, rt) == "D"

    # Separate counter for a different loop_guard step id.
    assert act.execute(s2, state, rt) == "A"
    assert act.execute(s2, state, rt) == "A"
    assert act.execute(s2, state, rt) == "D"

