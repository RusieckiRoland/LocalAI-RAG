# tests/test_dynamic_pipeline.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from code_query_engine.dynamic_pipeline import DynamicPipelineRunner
from code_query_engine.pipeline.action_registry import ActionRegistry
from code_query_engine.pipeline.definitions import PipelineDef, StepDef
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.state import PipelineState


class SetAnswerAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        state.answer_en = "ok"
        state.final_answer = "ok"
        state.query_type = "direct answer"
        return None


class Dummy:
    def __getattr__(self, name: str) -> Any:
        # allow any attribute access in tests
        return lambda *args, **kwargs: None


@dataclass
class StubLoader:
    pipeline: PipelineDef

    def load_by_name(self, name: str) -> PipelineDef:
        return self.pipeline


class StubValidator:
    def validate(self, pipeline: PipelineDef) -> None:
        # keep it simple in this wrapper test
        return


class DummyHistoryManager:
    def __init__(self, redis: Any, session_id: str) -> None:
        self.redis = redis
        self.session_id = session_id

    def start_user_query(self, model_input_en: str, original_pl: str) -> None:
        return


def test_dynamic_pipeline_runner_runs_via_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch HistoryManager used inside DynamicPipelineRunner
    import code_query_engine.dynamic_pipeline as dp

    monkeypatch.setattr(dp, "HistoryManager", DummyHistoryManager)

    registry = ActionRegistry()
    registry.register("set_answer", SetAnswerAction())

    pipeline = PipelineDef(
        name="wrapper-smoke",
        settings={"entry_step_id": "a"},
        steps=[
            StepDef(id="a", action="set_answer", raw={"id": "a", "action": "set_answer", "end": True}),
        ],
    )

    runner = DynamicPipelineRunner(
        pipelines_dir="tests/_does_not_matter_here",
        main_model=Dummy(),
        searcher=Dummy(),
        markdown_translator=Dummy(),
        translator_pl_en=Dummy(),
        logger=Dummy(),
    )

    # Override internals so the test is deterministic and does not depend on YAML files
    runner._loader = StubLoader(pipeline=pipeline)
    runner._validator = StubValidator()
    runner._engine = PipelineEngine(registry=registry)

    answer, query_type, steps_used, model_input_en = runner.run(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
        mock_redis=object(),
    )

    assert answer == "ok"
    assert query_type == "direct answer"
    assert steps_used == 1
    assert model_input_en == "q"
