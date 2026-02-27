from __future__ import annotations

import base64
import re

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

        # Do NOT emit a data: URI (sanitizers often strip it). Instead, embed the payload
        # as base64 in a data-* attribute and let the UI generate a downloadable Blob.
        xmi_b64 = base64.b64encode(xmi.encode("utf-8")).decode("ascii")

        lang = self._lang(state)
        if lang == "pl":
            label = "Eksportuj do EA (XMI)"
        else:
            label = "Export to EA (XMI)"

        return (
            '<a class="command-link command-ea-export" href="#" '
            f'data-xmi-b64="{xmi_b64}" data-filename="diagram.xmi">{label}</a>'
        )
