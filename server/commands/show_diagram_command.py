from __future__ import annotations

import re

from integrations.plant_uml.plantuml_check import PLANTUML_SERVER, encode_plantuml

from .base_command import BaseCommand


class ShowDiagramCommand(BaseCommand):
    command_type = "showDiagram"
    required_permission = "showDiagram"
    requires_sanitized_answer = True

    def build_link(self, answer_text: str, state) -> str | None:
        if not isinstance(answer_text, str) or not answer_text.strip():
            return None

        server = (PLANTUML_SERVER or "").strip().rstrip("/")
        if not server:
            return None

        match = re.search(r"@startuml.*?@enduml", answer_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None

        diagram = match.group(0)
        encoded = encode_plantuml(diagram)
        link = f"{server}/uml/{encoded}"

        if link in answer_text:
            return None

        lang = self._lang(state)
        if lang == "pl":
            label = "Otwórz diagram UML"
        else:
            label = "Open UML diagram"

        return f'<a class="command-link" href="{link}" target="_blank" rel="noopener noreferrer">{label}</a>'
