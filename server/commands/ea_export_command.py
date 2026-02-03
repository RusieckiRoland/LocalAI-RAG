from __future__ import annotations

import re
import urllib.parse

from integrations.ea.converter import puml_to_xmi

from .base_command import BaseCommand


class EaExportCommand(BaseCommand):
    command_type = "ea_export"
    required_permission = "ea_export"
    requires_sanitized_answer = True

    def build_link(self, answer_text: str, state) -> str | None:
        if not isinstance(answer_text, str) or not answer_text.strip():
            return None

        match = re.search(r"@startuml.*?@enduml", answer_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None

        diagram = match.group(0)
        try:
            xmi = puml_to_xmi(diagram, model_name="PUML Model")
        except Exception:
            return None

        data = urllib.parse.quote(xmi)
        href = f"data:application/xml;charset=utf-8,{data}"

        lang = self._lang(state)
        if lang == "pl":
            label = "Eksportuj do EA (XMI)"
        else:
            label = "Export to EA (XMI)"

        return (
            '<a class="command-link" '
            f'href="{href}" download="diagram.xmi">{label}</a>'
        )
