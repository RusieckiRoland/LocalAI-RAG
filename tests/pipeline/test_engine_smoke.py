from __future__ import annotations

from typing import Optional

from code_query_engine.pipeline.action_registry import ActionRegistry
from code_query_engine.pipeline.definitions import PipelineDef, StepDef
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator


class SetAnswerAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        state.answer_en = "ok"
        return None  # fall back to step.next


class FinalizeAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        state.final_answer = state.answer_en
        return None


class Dummy:
    pass


def test_engine_runs_to_end() -> None:
    registry = ActionRegistry()
    registry.register("set_answer", SetAnswerAction())
    registry.register("finalize", FinalizeAction())

    pipeline = PipelineDef(
        name="smoke",
        settings={"entry_step_id": "a"},
        steps=[
            StepDef(id="a", action="set_answer", raw={"id": "a", "action": "set_answer", "next": "b"}),
            StepDef(id="b", action="finalize", raw={"id": "b", "action": "finalize", "end": True}),
        ],
    )

    PipelineValidator().validate(pipeline)

    engine = PipelineEngine(registry)
    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    runtime = PipelineRuntime(
        pipeline_settings=pipeline.settings,
        main_model=Dummy(),
        searcher=Dummy(),
        markdown_translator=Dummy(),
        translator_pl_en=Dummy(),
        history_manager=Dummy(),
        logger=Dummy(),
        constants=Dummy(),
        add_plant_link=lambda x, y: x,
    )

    out = engine.run(pipeline, state, runtime)
    assert out.final_answer == "ok"
    assert out.steps_used == 2
