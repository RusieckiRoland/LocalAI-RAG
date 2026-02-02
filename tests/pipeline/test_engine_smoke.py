import pytest

import constants
from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator


class DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class DummyMarkdownTranslator:
    def translate(self, markdown_en: str) -> str:
        return markdown_en


class DummyHistory:
    def get_context_blocks(self):
        return []

    def add_iteration(self, followup, faiss_results):
        return None

    def set_final_answer(self, answer_en, answer_pl):
        return None


class DummyLogger:
    def log_interaction(self, **kwargs):
        return None


def test_engine_smoke_runs_to_end(tmp_path):
    # Arrange: local prompts dir (test-only, no production I/O)
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # call_model loads <prompts_dir>/<prompt_key>.txt
    (prompts_dir / "rejewski_router_v1.txt").write_text("SYS\n", encoding="utf-8")

    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
        f"""
YAMLpipeline:
  name: smoke

  settings:
    entry_step_id: call_model
    prompts_dir: "{str(prompts_dir)}"

  steps:
    - id: call_model
      action: call_model
      prompt_key: "rejewski_router_v1"
      user_parts:
        user_question:
          source: user_query
          template: "Q:{{}}\\n"
      next: finalize

    - id: finalize
      action: finalize
      end: true
""".strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)

    # call_model currently calls model.ask(prompt=..., system_prompt=None, **model_kwargs)
    # and does NOT pass consultant. Keep the stub permissive but still capture arguments.
    class _PromptModel:
        def __init__(self, outputs):
            self._outputs = list(outputs)
            self.calls = []

        def ask(self, *, prompt: str, system_prompt=None, consultant: str = "", **kwargs):
            self.calls.append(
                {"prompt": prompt, "consultant": consultant, "system_prompt": system_prompt, "kwargs": kwargs}
            )
            return self._outputs.pop(0) if self._outputs else ""

    model = _PromptModel(outputs=["[DIRECT:]"])
    rt = PipelineRuntime(
        pipeline_settings=pipe.settings,
        model=model,
        searcher=None,
        markdown_translator=DummyMarkdownTranslator(),
        translator_pl_en=DummyTranslator(),
        history_manager=DummyHistory(),
        logger=DummyLogger(),
        constants=constants,        
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x: x,
    )

    engine = PipelineEngine(build_default_action_registry())
    state = PipelineState(
        user_query="hi",
        session_id="s",
        consultant="rejewski",
        branch=None,
        snapshot_id="snap",
        translate_chat=False,
    )

    out = engine.run(pipe, state, rt)
    assert out.steps_used >= 1
    assert len(model.calls) == 1
    assert isinstance(model.calls[0]["prompt"], str)
    assert model.calls[0]["prompt"] != ""
