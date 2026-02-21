import constants

from code_query_engine.pipeline.action_registry import build_default_action_registry
from code_query_engine.pipeline.engine import PipelineEngine, PipelineRuntime
from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.state import PipelineState
from code_query_engine.pipeline.validator import PipelineValidator


class _DummyHistory:
    def get_context_blocks(self):
        return []

    def add_iteration(self, *args, **kwargs):
        return None

    def set_final_answer(self, *args, **kwargs):
        return None


class _DummyTranslator:
    def translate(self, text: str) -> str:
        return text


class _PrefixMarkdownTranslator:
    def __init__(self, prefix: str):
        self._prefix = prefix

    def translate_markdown(self, markdown_en: str) -> str:
        return f"{self._prefix}{markdown_en}"


class _CaptureModel:
    def __init__(self, out: str):
        self._out = out
        self.calls = []

    def ask(self, *, prompt: str, system_prompt=None, **kwargs):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "kwargs": kwargs})
        return self._out


def test_translate_out_if_needed_default_uses_markdown_translator(tmp_path):
    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
        """
YAMLpipeline:
  name: t
  settings:
    entry_step_id: translate_out
  steps:
    - id: translate_out
      action: translate_out_if_needed
      end: true
""".strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)

    rt = PipelineRuntime(
        pipeline_settings=pipe.settings,
        model=None,
        searcher=None,
        markdown_translator=_PrefixMarkdownTranslator(prefix="PL: "),
        translator_pl_en=_DummyTranslator(),
        history_manager=_DummyHistory(),
        logger=None,
        constants=constants,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x, consultant=None: x,
    )

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        translate_chat=True,
    )
    state.answer_neutral = "Hello"

    out = PipelineEngine(build_default_action_registry()).run(pipe, state, rt)
    assert out.answer_translated == "PL: Hello"


def test_translate_out_if_needed_use_main_model_translates_using_prompt_key(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "utility").mkdir(parents=True, exist_ok=True)
    (prompts_dir / "utility" / "translate_md_en_pl.txt").write_text(
        "You will receive between:\\n<<<MARKDOWN_EN\\n...\\nMARKDOWN_EN\\n",
        encoding="utf-8",
    )

    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(
        f"""
YAMLpipeline:
  name: t
  settings:
    entry_step_id: translate_out
    prompts_dir: "{str(prompts_dir)}"
  steps:
    - id: translate_out
      action: translate_out_if_needed
      use_main_model: true
      translate_prompt_key: utility\\translate_md_en_pl
      end: true
""".strip(),
        encoding="utf-8",
    )

    loader = PipelineLoader(pipelines_root=str(tmp_path))
    pipe = loader.load_from_path(str(yaml_path))
    PipelineValidator().validate(pipe)

    model = _CaptureModel(out="Witaj")
    rt = PipelineRuntime(
        pipeline_settings=pipe.settings,
        model=model,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=_DummyTranslator(),
        history_manager=_DummyHistory(),
        logger=None,
        constants=constants,
        graph_provider=None,
        token_counter=None,
        add_plant_link=lambda x, consultant=None: x,
    )

    state = PipelineState(
        user_query="q",
        session_id="s",
        consultant="rejewski",
        translate_chat=True,
    )
    state.answer_neutral = "Hello"

    out = PipelineEngine(build_default_action_registry()).run(pipe, state, rt)
    assert out.answer_translated == "Witaj"
    assert len(model.calls) == 1
    assert "<<<MARKDOWN_EN" in model.calls[0]["prompt"]
    assert "Hello" in model.calls[0]["prompt"]
    assert "MARKDOWN_EN" in model.calls[0]["prompt"]
