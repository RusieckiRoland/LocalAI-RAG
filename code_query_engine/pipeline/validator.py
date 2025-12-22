from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .definitions import PipelineDef, StepDef


class PipelineValidator:
    def __init__(self, *, allowed_actions: Optional[Set[str]] = None) -> None:
        # If provided, validate() will reject any step.action not present in this allowlist.
        self._allowed_actions = allowed_actions

    def validate(self, pipeline: PipelineDef) -> List[str]:
        warnings: List[str] = []

        steps_by_id = {s.id: s for s in pipeline.steps}

        entry = pipeline.settings.get("entry_step_id")
        if not entry or entry not in steps_by_id:
            raise ValueError(f"entry_step_id missing or unknown: {entry}")

        # If caller did not provide an allowlist, default to built-in actions.
        if self._allowed_actions is None:
            from .action_registry import build_default_action_registry

            reg = build_default_action_registry()
            # ActionRegistry stores actions in a dict {action_name: ActionInstance}
            self._allowed_actions = set(reg._actions.keys())  # type: ignore[attr-defined]

        for step in pipeline.steps:
            if self._allowed_actions is not None and step.action not in self._allowed_actions:
                raise ValueError(f"Unknown action: {step.action}")

            next_id = step.raw.get("next")
            if next_id and next_id not in steps_by_id:
                raise ValueError(f"Unknown step referenced: {next_id}")

            for branch_key, next_step in step.raw.items():
                if branch_key.startswith("on_") and isinstance(next_step, str):
                    if next_step not in steps_by_id:
                        raise ValueError(f"Unknown step referenced: {next_step}")

        # ---- Lint warnings (non-fatal) ----
        actions = [s.action for s in pipeline.steps]

        if "expand_dependency_tree" in actions and "fetch_more_context" not in actions:
            warnings.append("WARN: expand_dependency_tree used without fetch_more_context (no seed source).")

        if "fetch_node_texts" in actions and "expand_dependency_tree" not in actions:
            warnings.append("WARN: fetch_node_texts used without expand_dependency_tree.")

        # Heuristic: if an "answer" call_model step is listed before fetch_more_context, warn.
        answer_idx = None
        fetch_idx = None
        for idx, s in enumerate(pipeline.steps):
            if fetch_idx is None and s.action == "fetch_more_context":
                fetch_idx = idx
            if answer_idx is None and s.action == "call_model" and "answer" in (s.id or "").lower():
                answer_idx = idx

        if answer_idx is not None and fetch_idx is not None and answer_idx < fetch_idx:
            warnings.append("WARN: answer call_model appears before fetch_more_context.")

        return warnings

    def lint(self, pipeline: PipelineDef) -> List[str]:
        """Return non-fatal warnings about suspicious pipeline topology."""
        warnings: List[str] = []

        # 1) expand_graph without any obvious seed source.
        expand_idx = self._first_action_index(pipeline.steps, "expand_graph")
        if expand_idx is not None:
            has_seed_before = any(
                s.action in ("search", "fetch_more_context") for s in pipeline.steps[:expand_idx]
            )
            if not has_seed_before:
                warnings.append("expand_graph without seed_source")

        # 2) fetch_node_texts without expand_graph.
        fetch_texts_idx = self._first_action_index(pipeline.steps, "fetch_node_texts")
        if fetch_texts_idx is not None and expand_idx is None:
            warnings.append("fetch_node_texts without expand_graph")

        # 3) call_answer before fetch_node_texts.
        answer_idx = self._find_call_answer_index(pipeline.steps)
        if answer_idx is not None:
            if fetch_texts_idx is None or answer_idx < fetch_texts_idx:
                warnings.append("call_answer before fetch_node_texts")

        return warnings

    @staticmethod
    def _collect_step_refs(raw_step: Dict[str, Any]) -> List[str]:
        refs: List[str] = []

        nxt = raw_step.get("next")
        if isinstance(nxt, str) and nxt.strip():
            refs.append(nxt.strip())

        for k, v in raw_step.items():
            if not isinstance(k, str):
                continue
            if not k.startswith("on_"):
                continue
            if isinstance(v, str) and v.strip():
                refs.append(v.strip())

        return refs

    @staticmethod
    def _first_action_index(steps: List[StepDef], action_name: str) -> Optional[int]:
        for i, s in enumerate(steps):
            if s.action == action_name:
                return i
        return None

    @staticmethod
    def _find_call_answer_index(steps: List[StepDef]) -> Optional[int]:
        for i, s in enumerate(steps):
            if s.id == "call_answer":
                return i

            if s.action == "call_model":
                prompt_key = str(s.raw.get("prompt_key") or "")
                if "answer" in prompt_key:
                    return i

        return None
