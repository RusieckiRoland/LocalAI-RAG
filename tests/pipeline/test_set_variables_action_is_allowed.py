import pytest

from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator


class _NoopLogger:
    def log_interaction(self, **kwargs):
        return None


def test_set_variables_is_allowed_by_validator_and_runs(tmp_path):
    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
        """
YAMLpipeline:
  name: set_variables_smoke

  settings:
    entry_step_id: set_vars

  steps:
    - id: set_vars
      action: set_variables
      rules:
        - set: search_type
          value: "bm25"
      next: finalize

    - id: finalize
      action: finalize
      end: true
""".strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))

    # Must not raise "Unknown action: set_variables"
    PipelineValidator().validate(pipe)

    # Minimal runtime (finalize will just end; set_variables must mutate state)
    rt = PipelineRuntime(
        pipeline_settings=pipe.settings,
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=_NoopLogger(),
        constants=None,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    engine = PipelineEngine(build_default_action_registry())
    state = PipelineState(
        user_query="hi",
        session_id="s",
        consultant="rejewski",
        branch="develop",
        translate_chat=False,
    )

    out = engine.run(pipe, state, rt)

    assert getattr(state, "search_type", "") == "bm25"
    assert out.steps_used >= 1
