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
    from .actions.handle_prefix import HandlePrefixAction
    from .actions.translate_in_if_needed import TranslateInIfNeededAction
    from .actions.load_conversation_history import LoadConversationHistoryAction
    from .actions.check_context_budget import CheckContextBudgetAction
    from .actions.fetch_more_context import FetchMoreContextAction
    from .actions.expand_dependency_tree import ExpandDependencyTreeAction
    from .actions.fetch_node_texts import FetchNodeTextsAction
    from .actions.loop_guard import LoopGuardAction
    from .actions.finalize_heuristic import FinalizeHeuristicAction
    from .actions.persist_turn_and_finalize import PersistTurnAndFinalizeAction
    from .actions.finalize import FinalizeAction

    r = ActionRegistry()

    r.register("translate_in_if_needed", TranslateInIfNeededAction())
    r.register("load_conversation_history", LoadConversationHistoryAction())
    r.register("check_context_budget", CheckContextBudgetAction())
    r.register("call_model", CallModelAction())
    r.register("handle_prefix", HandlePrefixAction())
    r.register("fetch_more_context", FetchMoreContextAction())
    r.register("expand_dependency_tree", ExpandDependencyTreeAction())
    r.register("fetch_node_texts", FetchNodeTextsAction())
    r.register("loop_guard", LoopGuardAction())
    r.register("finalize_heuristic", FinalizeHeuristicAction())
    r.register("persist_turn_and_finalize", PersistTurnAndFinalizeAction())
    r.register("finalize", FinalizeAction())

    return r
