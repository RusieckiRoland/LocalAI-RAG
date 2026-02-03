from __future__ import annotations

from typing import Dict

from .base_command import BaseCommand
from .show_diagram_command import ShowDiagramCommand


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: Dict[str, BaseCommand] = {}

    def register(self, command: BaseCommand) -> None:
        key = (command.command_type or "").strip()
        if not key:
            raise ValueError("Command type is empty.")
        self._commands[key] = command

    def get(self, command_type: str) -> BaseCommand:
        key = (command_type or "").strip()
        if key not in self._commands:
            raise KeyError(f"Unknown command type: '{key}'. Registered: {sorted(self._commands.keys())}")
        return self._commands[key]


def build_default_command_registry() -> CommandRegistry:
    reg = CommandRegistry()
    reg.register(ShowDiagramCommand())
    return reg
