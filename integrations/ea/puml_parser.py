from __future__ import annotations

import re
import uuid
from typing import Dict, List, Tuple

from .model import Element, PumlModel, Relationship


_RE_ACTOR = re.compile(r"^actor\s+(?:\"(?P<name>[^\"]+)\"|(?P<name2>[^\s]+))\s+as\s+(?P<alias>[A-Za-z0-9_]+)", re.IGNORECASE)
_RE_USECASE = re.compile(r"^usecase\s+(?:\"(?P<name>[^\"]+)\"|(?P<name2>[^\s]+))\s+as\s+(?P<alias>[A-Za-z0-9_]+)", re.IGNORECASE)
_RE_REL_ASSOC = re.compile(r"^(?P<src>[A-Za-z0-9_]+)\s*--?>\s*(?P<dst>[A-Za-z0-9_]+)")
_RE_REL_INCLUDE_EXTEND = re.compile(
    r"^(?P<src>[A-Za-z0-9_]+)\s*\.>\s*(?P<dst>[A-Za-z0-9_]+)\s*:\s*<<(?P<kind>include|extend)>>",
    re.IGNORECASE,
)


def parse_puml(text: str, *, model_name: str = "PUML Model") -> PumlModel:
    """
    Parse a small, well-formed subset of PlantUML into a PumlModel.
    Supported elements: actor, usecase
    Supported relations: --> association, .> : <<include>> / <<extend>>
    """
    block = _extract_first_uml_block(text)
    model = PumlModel(name=model_name)

    alias_map: Dict[str, str] = {}

    for raw_line in block:
        line = _clean_line(raw_line)
        if not line:
            continue

        m = _RE_ACTOR.match(line)
        if m:
            name = (m.group("name") or m.group("name2") or "").strip()
            alias = m.group("alias").strip()
            _add_element(model, alias_map, element_type="Actor", name=name, alias=alias)
            continue

        m = _RE_USECASE.match(line)
        if m:
            name = (m.group("name") or m.group("name2") or "").strip()
            alias = m.group("alias").strip()
            _add_element(model, alias_map, element_type="UseCase", name=name, alias=alias)
            continue

        m = _RE_REL_INCLUDE_EXTEND.match(line)
        if m:
            src = m.group("src")
            dst = m.group("dst")
            kind = m.group("kind").lower()
            _add_relation(model, alias_map, kind.title(), src, dst)
            continue

        m = _RE_REL_ASSOC.match(line)
        if m:
            src = m.group("src")
            dst = m.group("dst")
            _add_relation(model, alias_map, "Association", src, dst)
            continue

    return model


def _extract_first_uml_block(text: str) -> List[str]:
    lines = (text or "").splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if start_idx is None and "@startuml" in line.lower():
            start_idx = i + 1
            continue
        if start_idx is not None and "@enduml" in line.lower():
            end_idx = i
            break
    if start_idx is None:
        return []
    if end_idx is None:
        end_idx = len(lines)
    return lines[start_idx:end_idx]


def _clean_line(line: str) -> str:
    # Remove comments and trim
    s = line.strip()
    if not s:
        return ""
    if s.startswith("'") or s.startswith("//"):
        return ""
    # Drop skinparam or direction directives
    if s.lower().startswith("skinparam"):
        return ""
    if s.lower().startswith("left to right"):
        return ""
    return s


def _add_element(model: PumlModel, alias_map: Dict[str, str], *, element_type: str, name: str, alias: str) -> None:
    if alias in alias_map:
        return
    el_id = _new_id()
    alias_map[alias] = el_id
    model.elements[el_id] = Element(element_id=el_id, element_type=element_type, name=name, alias=alias)


def _add_relation(model: PumlModel, alias_map: Dict[str, str], rel_type: str, src_alias: str, dst_alias: str) -> None:
    src_id = alias_map.get(src_alias)
    dst_id = alias_map.get(dst_alias)

    if not src_id:
        src_id = _new_id()
        alias_map[src_alias] = src_id
        model.elements[src_id] = Element(element_id=src_id, element_type="Actor", name=src_alias, alias=src_alias)
    if not dst_id:
        dst_id = _new_id()
        alias_map[dst_alias] = dst_id
        model.elements[dst_id] = Element(element_id=dst_id, element_type="UseCase", name=dst_alias, alias=dst_alias)

    model.relationships.append(
        Relationship(rel_id=_new_id(), rel_type=rel_type, source_id=src_id, target_id=dst_id)
    )


def _new_id() -> str:
    return uuid.uuid4().hex
