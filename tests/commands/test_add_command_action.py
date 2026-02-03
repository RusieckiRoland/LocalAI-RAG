import types

import integrations.plant_uml.plantuml_check as plantuml_check

from code_query_engine.pipeline.actions.add_command_action import AddCommandAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.state import PipelineState


def _make_state(*, allowed_commands, text):
    return PipelineState(
        user_query="q",
        session_id="s",
        consultant="ada",
        translate_chat=True,
        allowed_commands=allowed_commands,
        last_model_response=text,
    )


def test_add_command_action_appends_multiple_links(monkeypatch):
    monkeypatch.setattr(plantuml_check, "PLANTUML_SERVER", "https://plantuml.test")
    monkeypatch.setattr(plantuml_check, "encode_plantuml", lambda text: "ENCODED")

    import integrations.ea.converter as converter
    monkeypatch.setattr(converter, "puml_to_xmi", lambda text, model_name="PUML Model": "<xmi/>")

    text = """
    ```plantuml
    @startuml
    Alice -> Bob
    @enduml
    ```
    """

    state = _make_state(allowed_commands=["showDiagram", "ea_export"], text=text)
    step = StepDef(id="add", action="add_command_action", raw={"commands": [{"type": "showDiagram"}, {"type": "ea_export"}]})

    action = AddCommandAction()
    action.do_execute(step, state, runtime=None)

    out = state.last_model_response
    assert "command-links" in out
    assert "showDiagram" not in out  # not raw type
    assert "plantuml.test" in out
    assert "data:application/xml" in out


def test_add_command_action_respects_permissions(monkeypatch):
    monkeypatch.setattr(plantuml_check, "PLANTUML_SERVER", "https://plantuml.test")
    monkeypatch.setattr(plantuml_check, "encode_plantuml", lambda text: "ENCODED")

    text = "@startuml\nA->B\n@enduml"
    state = _make_state(allowed_commands=[], text=text)
    step = StepDef(id="add", action="add_command_action", raw={"commands": [{"type": "showDiagram"}]})

    action = AddCommandAction()
    action.do_execute(step, state, runtime=None)

    assert "command-links" not in (state.last_model_response or "")
