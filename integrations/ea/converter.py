from __future__ import annotations

from .puml_parser import parse_puml
from .xmi_writer import to_xmi


def puml_to_xmi(puml_text: str, *, model_name: str = "PUML Model") -> str:
    model = parse_puml(puml_text, model_name=model_name)
    return to_xmi(model)
