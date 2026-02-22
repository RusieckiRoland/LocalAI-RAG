from __future__ import annotations

import pytest

from code_query_engine.pipeline.definitions import PipelineDef, StepDef
from code_query_engine.pipeline.validator import PipelineValidator


def test_validator_requires_entry_step_id() -> None:
    p = PipelineDef(
        name="x",
        settings={"behavior_version": "0.2.0", "compat_mode": "latest"},
        steps=[StepDef(id="a", action="finalize", raw={"id": "a", "action": "finalize", "end": True})],
    )
    with pytest.raises(ValueError):
        PipelineValidator().validate(p)


def test_validator_entry_step_must_exist() -> None:
    p = PipelineDef(
        name="x",
        settings={"entry_step_id": "missing", "behavior_version": "0.2.0", "compat_mode": "latest"},
        steps=[StepDef(id="a", action="finalize", raw={"id": "a", "action": "finalize", "end": True})],
    )
    with pytest.raises(ValueError):
        PipelineValidator().validate(p)


def test_validator_transition_target_must_exist() -> None:
    p = PipelineDef(
        name="x",
        settings={"entry_step_id": "a", "behavior_version": "0.2.0", "compat_mode": "latest"},
        steps=[
            StepDef(id="a", action="translate_in_if_needed", raw={"id": "a", "action": "translate_in_if_needed", "next": "missing"}),
        ],
    )
    with pytest.raises(ValueError):
        PipelineValidator().validate(p)


def test_validator_translate_out_requires_translate_prompt_key_when_using_main_model() -> None:
    p = PipelineDef(
        name="x",
        settings={"entry_step_id": "t", "behavior_version": "0.2.0", "compat_mode": "latest"},
        steps=[
            StepDef(
                id="t",
                action="translate_out_if_needed",
                raw={"id": "t", "action": "translate_out_if_needed", "use_main_model": True, "end": True},
            ),
        ],
    )
    with pytest.raises(ValueError, match="translate_prompt_key"):
        PipelineValidator().validate(p)
