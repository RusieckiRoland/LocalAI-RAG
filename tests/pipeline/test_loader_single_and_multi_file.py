from __future__ import annotations

import textwrap
from pathlib import Path

from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.validator import PipelineValidator


def test_loader_can_load_single_pipeline_file_and_multi_pipeline_file(tmp_path: Path) -> None:
    pipelines_root = tmp_path / "pipelines"
    pipelines_root.mkdir(parents=True, exist_ok=True)

    # 1) Single-pipeline file (classic)
    single_path = pipelines_root / "single_one.yaml"
    single_path.write_text(
        textwrap.dedent(
            """
            YAMLpipeline:
              name: single_one
              settings:
                entry_step_id: a
                behavior_version: "0.2.0"
                compat_mode: latest
                top_k: 1
              steps:
                - id: a
                  action: finalize
                  end: true
            """
        ).strip(),
        encoding="utf-8",
    )

    # 2) Multi-pipeline file (new)
    multi_path = pipelines_root / "pack.yaml"
    multi_path.write_text(
        textwrap.dedent(
            """
            YAMLpipelines:
              - name: multi_a
                settings:
                  entry_step_id: a
                  behavior_version: "0.2.0"
                  compat_mode: latest
                  top_k: 2
                steps:
                  - id: a
                    action: finalize
                    end: true

              - name: multi_b
                settings:
                  entry_step_id: b
                  behavior_version: "0.2.0"
                  compat_mode: latest
                  top_k: 3
                steps:
                  - id: b
                    action: finalize
                    end: true
            """
        ).strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(pipelines_root))

    # Load single (by name -> should hit <name>.yaml directly)
    p_single = loader.load_by_name("single_one")
    PipelineValidator().validate(p_single)
    assert p_single.name == "single_one"
    assert int(p_single.settings.get("top_k")) == 1
    assert p_single.settings.get("entry_step_id") == "a"

    # Load multi (by name -> should be found in index scan)
    p_multi_a = loader.load_by_name("multi_a")
    PipelineValidator().validate(p_multi_a)
    assert p_multi_a.name == "multi_a"
    assert int(p_multi_a.settings.get("top_k")) == 2
    assert p_multi_a.settings.get("entry_step_id") == "a"

    # Load multi by explicit path + pipeline_name selector
    p_multi_b = loader.load_from_path(str(multi_path), pipeline_name="multi_b")
    PipelineValidator().validate(p_multi_b)
    assert p_multi_b.name == "multi_b"
    assert int(p_multi_b.settings.get("top_k")) == 3
    assert p_multi_b.settings.get("entry_step_id") == "b"
