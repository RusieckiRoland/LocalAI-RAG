import pytest

u = pytest.importorskip("common.utils")
parse_bool = getattr(u, "parse_bool")
sanitize_uml_answer = getattr(u, "sanitize_uml_answer")

pytestmark = pytest.mark.unit

def test_parse_bool_variants():
    for v in ["1", "true", " TRUE ", "on", "y", "yes"]:
        assert parse_bool(v) is True
    for v in ["0", "false", " off ", "n", "no"]:
        assert parse_bool(v) is False
    assert parse_bool(2) is True
    assert parse_bool(0) is False
    class X:
        pass
    assert parse_bool(X(), default=True) is True



def test_sanitize_uml_answer_fenced_and_global():
    # Build a fenced PlantUML block without embedding literal ``` in this source
    fence = "`" * 3
    fenced = (
        "text\n"
        + fence + "plantuml\n"
        "@startuml\n"
        "A->B\n"
        "@enduml\n"
        + fence + "\n"
        "http://link"
    )
    out1 = sanitize_uml_answer(fenced)
    assert "@startuml" in out1 and "@enduml" in out1 and "http" not in out1

    global_md = (
        "x\n"
        "@startuml\n"
        "Alice->Bob\n"
        "@enduml\n"
        "x"
    )
    out2 = sanitize_uml_answer(global_md)
    assert "@startuml" in out2 and "@enduml" in out2
