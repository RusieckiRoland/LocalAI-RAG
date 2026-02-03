# code_query_engine/pipeline/action_registry.py
from __future__ import annotations

from typing import Dict


class ActionRegistry:
    """Simple name->action registry used by PipelineEngine."""

    def __init__(self) -> None:
        self._actions: Dict[str, object] = {}

    def register(self, name: str, action: object) -> None:
        key = (name or "").strip()
        if not key:
            raise ValueError("Action name is empty.")
        self._actions[key] = action

    def get(self, name: str) -> object:
        key = (name or "").strip()
        if key not in self._actions:
            raise KeyError(f"Unknown action: '{key}'. Registered: {sorted(self._actions.keys())}")
        return self._actions[key]


def build_default_action_registry() -> ActionRegistry:
    """
    Builder that wires all built-in actions.
    IMPORTANT: lazy imports here avoid circular imports:
      engine -> action_registry -> actions -> engine
    """
    # Lazy imports (MUST be inside the function)
    from .actions.call_model import CallModelAction
    from .actions.prefix_router import PrefixRouterAction
    from .actions.translate_in_if_needed import TranslateInIfNeededAction
    from .actions.translate_out_if_needed import TranslateOutIfNeededAction
    from .actions.load_conversation_history import LoadConversationHistoryAction
    from .actions.check_context_budget import CheckContextBudgetAction
    from .actions.search_nodes import SearchNodesAction
    from .actions.expand_dependency_tree import ExpandDependencyTreeAction
    from .actions.fetch_node_texts import FetchNodeTextsAction
    from .actions.loop_guard import LoopGuardAction    
    from .actions.finalize import FinalizeAction
    from .actions.set_variables import SetVariablesAction
    from .actions.add_command_action import AddCommandAction

    r = ActionRegistry()

    r.register("translate_in_if_needed", TranslateInIfNeededAction())
    r.register("translate_out_if_needed", TranslateOutIfNeededAction())
    r.register("load_conversation_history", LoadConversationHistoryAction())
    r.register("check_context_budget", CheckContextBudgetAction())
    r.register("call_model", CallModelAction())
    r.register("prefix_router", PrefixRouterAction())
    r.register("search_nodes", SearchNodesAction())
    r.register("expand_dependency_tree", ExpandDependencyTreeAction())
    r.register("fetch_node_texts", FetchNodeTextsAction())
    r.register("loop_guard", LoopGuardAction())   
    r.register("add_command_action", AddCommandAction())
    r.register("finalize", FinalizeAction())
    r.register("set_variables", SetVariablesAction())

    return r
