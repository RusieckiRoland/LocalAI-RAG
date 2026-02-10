# code_query_engine/pipeline/validator.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple


# NOTE: This validator is intentionally "DbC + backward-compatible":
# - hard errors for broken references / missing required fields
# - warnings (not errors) for missing optional routing branches (legacy pipelines)


class PipelineValidator:
    """
    Validates pipeline structure (hard errors) and returns lint warnings (soft issues).
    """

    # Keep this list in sync with build_default_action_registry()
    _KNOWN_ACTIONS = {
        "call_model",
        "prefix_router",
        "translate_in_if_needed",
        "translate_out_if_needed",
        "load_conversation_history",
        "search_nodes",
        "expand_dependency_tree",
        "fetch_node_texts",
        "finalize",      
        "loop_guard",
        "set_variables",
        "add_command_action",
        "manage_context_budget",
    }

    def validate(self, pipeline: Any) -> List[str]:
        warnings: List[str] = []

        if pipeline is None:
            raise ValueError("pipeline is None")

        settings = getattr(pipeline, "settings", None)
        if settings is None or not isinstance(settings, dict):
            raise ValueError("pipeline.settings must be a dict")

        # IMPORTANT: validate entry_step_id before steps (tests expect this)
        entry_step_id = settings.get("entry_step_id")
        if not (isinstance(entry_step_id, str) and entry_step_id.strip()):
            raise ValueError("pipeline.settings.entry_step_id is required")

        steps = getattr(pipeline, "steps", None)
        if not isinstance(steps, list) or not steps:
            raise ValueError("pipeline.steps must be a non-empty list")

        steps_by_id: Dict[str, Any] = {}
        for s in steps:
            sid = getattr(s, "id", None)
            if not (isinstance(sid, str) and sid.strip()):
                raise ValueError("each step must have a non-empty string id")
            if sid in steps_by_id:
                raise ValueError(f"duplicate step id: {sid}")
            steps_by_id[sid] = s

        if entry_step_id not in steps_by_id:
            raise ValueError(f"entry_step_id references unknown step: {entry_step_id}")

        for s in steps:
            self._validate_step_common(s, steps_by_id)
            action = getattr(s, "action", None)

            if action == "call_model":
                self._validate_call_model(s)
            elif action == "prefix_router":
                self._validate_prefix_router_contract(s, steps_by_id, warnings)

        warnings.extend(self._lint_pipeline(steps))
        return warnings

    def _validate_step_common(self, step: Any, steps_by_id: Dict[str, Any]) -> None:
        action = getattr(step, "action", None)
        sid = getattr(step, "id", None)
        raw = getattr(step, "raw", None)

        if not (isinstance(action, str) and action.strip()):
            raise ValueError(f"step {sid}: action is required")

        if action not in self._KNOWN_ACTIONS:
            # tests expect "Unknown action" casing
            raise ValueError(f"Unknown action: {action}")

        if not isinstance(raw, dict):
            raise ValueError(f"step {sid}: raw dict is required")

        nxt = raw.get("next")
        end = raw.get("end")

        if nxt is not None:
            if not (isinstance(nxt, str) and nxt.strip()):
                raise ValueError(f"step {sid}: next must be a non-empty string if present")
            if nxt.strip() not in steps_by_id:
                raise ValueError(f"step {sid}: next references unknown step: {nxt}")

        if end is not None and not isinstance(end, bool):
            raise ValueError(f"step {sid}: end must be boolean if present")

    def _validate_call_model(self, step: Any) -> None:
        raw = step.raw
        sid = step.id

        prompt_key = raw.get("prompt_key")
        if not (isinstance(prompt_key, str) and prompt_key.strip()):
            raise ValueError(f"step {sid}: call_model requires prompt_key")

    def _validate_prefix_router_contract(
        self,
        step: Any,
        steps_by_id: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        raw = step.raw
        sid = step.id

        on_other = raw.get("on_other")
        if not (isinstance(on_other, str) and on_other.strip()):
            raise ValueError("prefix_router contract broken: on_other is required")
        if on_other.strip() not in steps_by_id:
            raise ValueError(
                f"prefix_router contract broken: on_other references unknown step: {on_other}"
            )

        prefixes: List[Tuple[str, str]] = []
        for k, v in raw.items():
            if isinstance(k, str) and k.endswith("_prefix") and isinstance(v, str) and v.strip():
                prefixes.append((k, v.strip()))

        if not prefixes:
            warnings.append(f"prefix_router {sid}: no *_prefix keys defined")

        prefix_values = [v for _, v in prefixes]
        if len(prefix_values) != len(set(prefix_values)):
            raise ValueError("prefix_router contract broken: duplicate *_prefix values detected")

        required_pairs = [
            ("semantic_prefix", "on_semantic"),
            ("bm25_prefix", "on_bm25"),
            ("hybrid_prefix", "on_hybrid"),
            ("semantic_rerank_prefix", "on_semantic_rerank"),
            ("direct_prefix", "on_direct"),
            ("answer_prefix", "on_answer"),
            ("followup_prefix", "on_followup"),
        ]

        for prefix_key, on_key in required_pairs:
            prefix_val = raw.get(prefix_key)
            if isinstance(prefix_val, str) and prefix_val.strip():
                target = raw.get(on_key)

                # Missing branch = warning (backward compatible)
                if not (isinstance(target, str) and target.strip()):
                    warnings.append(
                        f"prefix_router {sid}: {prefix_key} is set but {on_key} is missing"
                    )
                    continue

                target_id = target.strip()
                if target_id not in steps_by_id:
                    raise ValueError(
                        f"prefix_router contract broken: {on_key} references unknown step: {target_id}"
                    )

        # Validate any explicit on_* keys that exist
        for k, v in raw.items():
            if isinstance(k, str) and k.startswith("on_") and isinstance(v, str) and v.strip():
                if v.strip() not in steps_by_id:
                    raise ValueError(
                        f"prefix_router contract broken: {k} references unknown step: {v}"
                    )

    def _lint_pipeline(self, steps: List[Any]) -> List[str]:
        warnings: List[str] = []

        actions = [getattr(s, "action", "") for s in steps]
        ids = [getattr(s, "id", "") for s in steps]

        has_expand = "expand_dependency_tree" in actions
        has_fetch_more = "search_nodes" in actions
        has_fetch_texts = "fetch_node_texts" in actions

        if has_fetch_texts and not has_expand:
            warnings.append("fetch_node_texts without expand_dependency_tree")

        if has_expand and not has_fetch_more:
            warnings.append("expand_dependency_tree without seed source")

        try:
            idx_answer = ids.index("call_answer")
        except ValueError:
            idx_answer = -1

        try:
            idx_fetch = actions.index("search_nodes")
        except ValueError:
            idx_fetch = -1

        if idx_answer >= 0 and idx_fetch >= 0 and idx_answer < idx_fetch:
            warnings.append("answer before search_nodes")

        return warnings
