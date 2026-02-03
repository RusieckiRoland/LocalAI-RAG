from __future__ import annotations

import re

from common.utils import sanitize_uml_answer
from integrations.plant_uml.plantuml_check import PLANTUML_SERVER, encode_plantuml

from .base_command import BaseCommand, CommandResult


class ShowDiagramCommand(BaseCommand):
    command_type = "showDiagram"
    required_permission = "showDiagram"

    def apply(self, answer_text: str, state) -> CommandResult:
        if not isinstance(answer_text, str) or not answer_text.strip():
            return CommandResult(appended=False, output=answer_text)

        server = (PLANTUML_SERVER or "").strip().rstrip("/")
        if not server:
            return CommandResult(appended=False, output=answer_text)

        match = re.search(r"@startuml.*?@enduml", answer_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return CommandResult(appended=False, output=answer_text)

        diagram = match.group(0)
        encoded = encode_plantuml(diagram)
        link = f"{server}/uml/{encoded}"

        if link in answer_text:
            return CommandResult(appended=False, output=answer_text)

        lang = self._lang(state)
        if lang == "pl":
            label = "Otwórz diagram UML"
        else:
            label = "Open UML diagram"

        normalized = sanitize_uml_answer(answer_text)
        html = f'\n\n<a href="{link}" target="_blank" rel="noopener noreferrer">{label}</a>'
        return CommandResult(appended=True, output=f"{normalized}{html}")
