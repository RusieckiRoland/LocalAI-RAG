from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from code_query_engine.dynamic_pipeline import DynamicPipelineRunner
from code_query_engine.pipeline.definitions import PipelineDef, StepDef
from code_query_engine.pipeline.lockfile import (
    Lockfile,
    apply_lockfile,
    generate_lockfile,
    load_lockfile,
    lockfile_path_for_yaml,
    serialize_lockfile,
    write_lockfile,
)


class _Dummy:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _pipeline(settings=None, steps=None) -> PipelineDef:
    return PipelineDef(
        name="p",
        settings=settings or {"entry_step_id": "a", "behavior_version": "0.2.0", "compat_mode": "latest"},
        steps=steps
        or [
            StepDef(id="a", action="search_nodes", raw={"id": "a", "action": "search_nodes", "search_type": "bm25"}),
        ],
    )


def test_lockfile_generation_is_deterministic():
    pipeline = _pipeline()
    lock1 = serialize_lockfile(generate_lockfile(pipeline))
    lock2 = serialize_lockfile(generate_lockfile(pipeline))
    assert json.dumps(lock1, sort_keys=True) == json.dumps(lock2, sort_keys=True)


def test_apply_lockfile_fails_on_missing_action_entry():
    pipeline = _pipeline(
        steps=[
            StepDef(id="a", action="search_nodes", raw={"id": "a", "action": "search_nodes"}),
            StepDef(id="b", action="finalize", raw={"id": "b", "action": "finalize", "end": True}),
        ]
    )
    lock = Lockfile(
        lock_version=1,
        pipeline_name="p",
        behavior_version="0.2.0",
        actions={"search_nodes": {"behavior": "0.2.0", "defaults": {}, "allowed_keys": None}},
    )
    with pytest.raises(ValueError, match="missing action entry"):
        apply_lockfile(pipeline, lock)


def test_apply_lockfile_fails_on_unknown_step_keys():
    pipeline = _pipeline(
        steps=[
            StepDef(
                id="a",
                action="search_nodes",
                raw={"id": "a", "action": "search_nodes", "search_type": "bm25", "unknown_key": 1},
            ),
        ]
    )
    lock = Lockfile(
        lock_version=1,
        pipeline_name="p",
        behavior_version="0.2.0",
        actions={
            "search_nodes": {
                "behavior": "0.2.0",
                "defaults": {},
                "allowed_keys": ["id", "action", "search_type"],
            }
        },
    )
    with pytest.raises(ValueError, match="not allowed by lockfile"):
        apply_lockfile(pipeline, lock)


def test_dynamic_pipeline_locked_requires_matching_behavior_version(tmp_path: Path) -> None:
    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
        """
YAMLpipeline:
  name: p
  settings:
    entry_step_id: a
    behavior_version: "0.2.0"
    compat_mode: locked
  steps:
    - id: a
      action: finalize
      end: true
""".strip(),
        encoding="utf-8",
    )

    lock_path = lockfile_path_for_yaml(yaml_path)
    lock = Lockfile(
        lock_version=1,
        pipeline_name="p",
        behavior_version="0.1.0",
        actions={"finalize": {"behavior": "0.1.0", "defaults": {}, "allowed_keys": None}},
    )
    write_lockfile(lockfile=lock, path=lock_path)

    pipeline = PipelineDef(
        name="p",
        settings={"entry_step_id": "a", "behavior_version": "0.2.0", "compat_mode": "locked"},
        steps=[StepDef(id="a", action="finalize", raw={"id": "a", "action": "finalize", "end": True})],
    )

    @dataclass
    class _StubLoader:
        def load_by_name(self, name: str) -> PipelineDef:
            return pipeline

        def resolve_files_by_name(self, name: str):
            return [yaml_path]

    runner = DynamicPipelineRunner(
        pipelines_dir=str(tmp_path),
        model=_Dummy(),
        retrieval_backend=_Dummy(),
        markdown_translator=_Dummy(),
        translator_pl_en=_Dummy(),
        logger=_Dummy(),
    )
    runner._loader = _StubLoader()

    with pytest.raises(ValueError, match="behavior_version"):
        runner.run(
            user_query="q",
            session_id="s",
            user_id=None,
            consultant="rejewski",
            branch="",
            snapshot_id="test-snapshot",
            translate_chat=False,
            mock_redis=object(),
        )

