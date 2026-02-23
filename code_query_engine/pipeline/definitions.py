# code_query_engine/pipeline/definitions.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class StepDef:
    """Single pipeline step definition (raw dict kept for flexibility)."""
    id: str
    action: str
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def next(self) -> Optional[str]:
        return self.raw.get("next")

    @property
    def end(self) -> bool:
        return bool(self.raw.get("end") is True)


@dataclass(frozen=True)
class PipelineDef:
    """Loaded and merged pipeline definition."""
    name: str
    settings: Dict[str, Any]
    steps: List[StepDef]

    def steps_by_id(self) -> Dict[str, StepDef]:
        return {s.id: s for s in self.steps}


def parse_pipeline_doc(doc: Dict[str, Any]) -> PipelineDef:
    """
    Accepts a YAML dict with root key: YAMLpipeline
    Returns a strongly-typed PipelineDef while keeping raw step dicts.
    """
    root = doc.get("YAMLpipeline")
    if not isinstance(root, dict):
        raise ValueError("Invalid pipeline YAML: missing root 'YAMLpipeline' mapping.")

    name = (root.get("name") or "").strip()
    if not name:
        raise ValueError("Invalid pipeline YAML: YAMLpipeline.name is required.")

    settings = root.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("Invalid pipeline YAML: YAMLpipeline.settings must be a mapping.")

    raw_steps = root.get("steps") or []
    if not isinstance(raw_steps, list):
        raise ValueError("Invalid pipeline YAML: YAMLpipeline.steps must be a list.")

    steps: List[StepDef] = []
    for s in raw_steps:
        if not isinstance(s, dict):
            raise ValueError("Invalid pipeline YAML: each step must be a mapping.")
        sid = (s.get("id") or "").strip()
        action = (s.get("action") or "").strip()
        if not sid:
            raise ValueError("Invalid pipeline YAML: each step must have non-empty 'id'.")
        if not action:
            raise ValueError(f"Invalid pipeline YAML: step '{sid}' must have non-empty 'action'.")
        steps.append(StepDef(id=sid, action=action, raw=s))

    return PipelineDef(name=name, settings=settings, steps=steps)
