# code_query_engine/pipeline/validator.py
from __future__ import annotations

from typing import Any, Dict, List, Set

from .definitions import PipelineDef


class PipelineValidator:
    """Validates step graph references and deterministic entry step."""

    def validate(self, pipeline: PipelineDef) -> None:
        steps_by_id = pipeline.steps_by_id()

        entry = (pipeline.settings.get("entry_step_id") or "").strip()
        if not entry:
            raise ValueError("settings.entry_step_id is required (deterministic start).")
        if entry not in steps_by_id:
            raise ValueError(f"settings.entry_step_id '{entry}' not found in steps.")

        for step in pipeline.steps:
            raw = step.raw
            refs = self._collect_step_refs(raw)
            for r in refs:
                if r not in steps_by_id:
                    raise ValueError(f"Step '{step.id}' references missing step id: '{r}'.")

    def _collect_step_refs(self, raw_step: Dict[str, Any]) -> List[str]:
        refs: List[str] = []
        nxt = raw_step.get("next")
        if isinstance(nxt, str) and nxt.strip():
            refs.append(nxt.strip())

        # any "on_*" transition must reference an existing step id
        for k, v in raw_step.items():
            if k.startswith("on_") and isinstance(v, str) and v.strip():
                refs.append(v.strip())

        return refs
