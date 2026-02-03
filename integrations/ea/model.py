from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Element:
    element_id: str
    element_type: str  # e.g. "Actor", "UseCase"
    name: str
    alias: Optional[str] = None


@dataclass
class Relationship:
    rel_id: str
    rel_type: str  # Association | Include | Extend
    source_id: str
    target_id: str


@dataclass
class PumlModel:
    name: str
    elements: Dict[str, Element] = field(default_factory=dict)  # key: element_id
    relationships: List[Relationship] = field(default_factory=list)

    def by_alias(self) -> Dict[str, Element]:
        out: Dict[str, Element] = {}
        for el in self.elements.values():
            if el.alias:
                out[el.alias] = el
        return out
