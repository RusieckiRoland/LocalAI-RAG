from __future__ import annotations

from pathlib import Path

from code_query_engine.pipeline.loader import PipelineLoader


def test_loader_extends_relative_path_and_merges_settings_and_steps(tmp_path: Path) -> None:
    pipelines_dir = tmp_path / "pipelines"
    base_dir = pipelines_dir / "base"
    base_dir.mkdir(parents=True)

    base_yaml = base_dir / "marian_rejewski_code_analysis_base.yaml"
    child_yaml = pipelines_dir / "rejewski.yaml"

    base_yaml.write_text(
        """
YAMLpipeline:
  name: marian_rejewski_code_analysis_base
  settings:
    entry_step_id: a
    behavior_version: "0.2.0"
    compat_mode: latest
    max_history_tokens: 100
    nested:
      x: 1
      y: 2
  steps:
    - id: a
      action: translate_in_if_needed
      next: b
    - id: b
      action: finalize
      end: true
""".strip(),
        encoding="utf-8",
    )

    child_yaml.write_text(
        """
YAMLpipeline:
  name: marian_rejewski_code_analysis_nopCommerce_develop
  extends: ./base/marian_rejewski_code_analysis_base.yaml
  settings:
    behavior_version: "0.2.0"
    compat_mode: latest
    max_history_tokens: 250
    nested:
      y: 999
      z: 3
  steps:
    - id: a
      action: translate_in_if_needed
      next: c
    - id: c
      action: finalize
      end: true
""".strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(pipelines_dir))
    pipeline = loader.load_from_path(str(child_yaml))

    assert pipeline.settings["entry_step_id"] == "a"
    assert pipeline.settings["max_history_tokens"] == 250
    assert pipeline.settings["nested"]["x"] == 1
    assert pipeline.settings["nested"]["y"] == 999
    assert pipeline.settings["nested"]["z"] == 3

    ids = [s.id for s in pipeline.steps]
    assert ids == ["a", "b", "c"]
    assert pipeline.steps_by_id()["a"].raw.get("next") == "c"
