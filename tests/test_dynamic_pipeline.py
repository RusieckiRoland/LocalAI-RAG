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
        state.answer_neutral = "ok"
        state.final_answer = "ok"
        state.query_type = "direct answer"
        return None


class Dummy:
    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


@dataclass
class StubLoader:
    pipeline: PipelineDef

    def load_by_name(self, name: str) -> PipelineDef:
        return self.pipeline


class StubValidator:
    def validate(self, pipeline: PipelineDef) -> None:
        return


class DummyHistoryManager:
    def __init__(self, redis: Any, session_id: str, user_id: Optional[str] = None) -> None:
        self.redis = redis
        self.session_id = session_id
        self.user_id = user_id

    def start_user_query(self, model_input_en: str, original_pl: str, user_id: Optional[str] = None) -> None:
        return

    def set_final_answer(self, en: str, answer_translated: Optional[str] = None) -> None:
        return

    def get_context_blocks(self) -> list[str]:
        return []


def test_dynamic_pipeline_runner_runs_via_engine(monkeypatch: pytest.MonkeyPatch) -> None:
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
        model=Dummy(),
        retrieval_backend=Dummy(),
        markdown_translator=Dummy(),
        translator_pl_en=Dummy(),
        logger=Dummy(),
    )

    runner._loader = StubLoader(pipeline=pipeline)
    runner._validator = StubValidator()
    runner._engine = PipelineEngine(registry=registry)

    answer, query_type, steps_used, model_input_en = runner.run(
        user_query="q",
        session_id="s",
        user_id=None,
        consultant="rejewski",
        branch="",
        snapshot_id="test-snapshot",
        translate_chat=False,
        mock_redis=object(),
    )

    assert answer == "ok"
    assert query_type == "direct answer"
    assert steps_used == 1
    assert model_input_en == "q"
