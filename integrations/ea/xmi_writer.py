from __future__ import annotations

import datetime
import uuid
from typing import Dict, List, Tuple

from .model import Element, PumlModel, Relationship


UML_NS = "omg.org/UML1.3"


def to_xmi(model: PumlModel) -> str:
    """
    Generate EA-friendly XMI 1.1 with a Use Case Diagram + basic layout.
    This is a minimal, clean structure based on EA exports.
    """
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    model_id = _mx_id()
    package_id = _eapk_id()
    diagram_id = _eaid()

    elements = list(model.elements.values())
    associations = list(model.relationships)

    layout = _layout_elements(elements)

    # Build XML manually for predictable ordering
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="windows-1252" standalone="no" ?>')
    lines.append(f'<XMI xmi.version="1.1" xmlns:UML="{UML_NS}" timestamp="{now}">')
    lines.append("  <XMI.header>")
    lines.append("    <XMI.documentation>")
    lines.append("      <XMI.exporter>Enterprise Architect</XMI.exporter>")
    lines.append("      <XMI.exporterVersion>2.5</XMI.exporterVersion>")
    lines.append("      <XMI.exporterID>1716</XMI.exporterID>")
    lines.append("    </XMI.documentation>")
    lines.append("  </XMI.header>")
    lines.append("  <XMI.content>")
    lines.append(f"    <UML:Model name=\"EA Model\" xmi.id=\"{model_id}\">")
    lines.append("      <UML:Namespace.ownedElement>")
    lines.append(
        f"        <UML:Package name=\"{_xml_escape(model.name or 'PUML Model')}\" xmi.id=\"{package_id}\" isRoot=\"false\" isLeaf=\"false\" isAbstract=\"false\" visibility=\"public\">"
    )
    lines.append("          <UML:Namespace.ownedElement>")

    # Elements
    for el in elements:
        lines.extend(_element_xml(el, package_id, now))

    # Relationships
    for rel in associations:
        lines.extend(_relationship_xml(rel))

    lines.append("          </UML:Namespace.ownedElement>")
    lines.append("        </UML:Package>")

    # Diagram
    lines.extend(_diagram_xml(diagram_id, package_id, elements, associations, layout, now))

    lines.append("      </UML:Namespace.ownedElement>")
    lines.append("    </UML:Model>")
    lines.append("  </XMI.content>")
    lines.append("  <XMI.difference/>")
    lines.append("</XMI>")

    return "\n".join(lines) + "\n"


def _element_xml(el: Element, package_id: str, now: str) -> List[str]:
    name = _xml_escape(el.name or el.alias or "Unnamed")
    tag = "UML:Actor" if el.element_type.lower() == "actor" else "UML:UseCase"
    return [
        f"            <{tag} name=\"{name}\" xmi.id=\"{el.element_id}\" visibility=\"public\" namespace=\"{package_id}\" isRoot=\"false\" isLeaf=\"false\" isAbstract=\"false\">",
        "              <UML:ModelElement.taggedValue>",
        f"                <UML:TaggedValue tag=\"ea_stype\" value=\"{el.element_type}\"/>",
        f"                <UML:TaggedValue tag=\"package\" value=\"{package_id}\"/>",
        f"                <UML:TaggedValue tag=\"date_created\" value=\"{now}\"/>",
        f"                <UML:TaggedValue tag=\"date_modified\" value=\"{now}\"/>",
        "              </UML:ModelElement.taggedValue>",
        f"            </{tag}>",
    ]


def _relationship_xml(rel: Relationship) -> List[str]:
    # Represent include/extend as stereotyped Association (EA export style)
    stereotype = None
    subtype = None
    if rel.rel_type.lower() == "include":
        stereotype = "include"
        subtype = "Includes"
    elif rel.rel_type.lower() == "extend":
        stereotype = "extend"
        subtype = "Extends"

    lines = [
        f"            <UML:Association xmi.id=\"{rel.rel_id}\" visibility=\"public\" isRoot=\"false\" isLeaf=\"false\" isAbstract=\"false\">"
    ]

    if stereotype:
        lines.append("              <UML:ModelElement.stereotype>")
        lines.append(f"                <UML:Stereotype name=\"{stereotype}\"/>")
        lines.append("              </UML:ModelElement.stereotype>")

    lines.append("              <UML:ModelElement.taggedValue>")
    if stereotype:
        lines.append(f"                <UML:TaggedValue tag=\"subtype\" value=\"{subtype}\"/>")
        lines.append(f"                <UML:TaggedValue tag=\"stereotype\" value=\"{stereotype}\"/>")
    lines.append("              </UML:ModelElement.taggedValue>")

    lines.append("              <UML:Association.connection>")
    lines.append(
        f"                <UML:AssociationEnd visibility=\"public\" aggregation=\"none\" isOrdered=\"false\" isNavigable=\"false\" type=\"{rel.source_id}\"/>"
    )
    lines.append(
        f"                <UML:AssociationEnd visibility=\"public\" aggregation=\"none\" isOrdered=\"false\" isNavigable=\"true\" type=\"{rel.target_id}\"/>"
    )
    lines.append("              </UML:Association.connection>")
    lines.append("            </UML:Association>")
    return lines


def _diagram_xml(
    diagram_id: str,
    package_id: str,
    elements: List[Element],
    relationships: List[Relationship],
    layout: Dict[str, Tuple[int, int, int, int]],
    now: str,
) -> List[str]:
    lines: List[str] = []
    lines.append(
        f"        <UML:Diagram name=\"{_xml_escape('PUML Model')}\" xmi.id=\"{diagram_id}\" diagramType=\"UseCaseDiagram\" owner=\"{package_id}\" toolName=\"Enterprise Architect 2.5\">"
    )
    lines.append("          <UML:ModelElement.taggedValue>")
    lines.append("            <UML:TaggedValue tag=\"version\" value=\"1.0\"/>")
    lines.append(f"            <UML:TaggedValue tag=\"created_date\" value=\"{now}\"/>")
    lines.append(f"            <UML:TaggedValue tag=\"modified_date\" value=\"{now}\"/>")
    lines.append(f"            <UML:TaggedValue tag=\"package\" value=\"{package_id}\"/>")
    lines.append("            <UML:TaggedValue tag=\"type\" value=\"Use Case\"/>")
    lines.append("          </UML:ModelElement.taggedValue>")

    lines.append("          <UML:Diagram.element>")

    seq = 1
    for el in elements:
        geom = layout.get(el.element_id)
        if not geom:
            continue
        left, top, right, bottom = geom
        lines.append(
            f"            <UML:DiagramElement geometry=\"Left={left};Top={top};Right={right};Bottom={bottom};\" subject=\"{el.element_id}\" seqno=\"{seq}\" style=\"DUID={_duid()};\"/>"
        )
        seq += 1

    # Edge elements for relationships
    for rel in relationships:
        lines.append(
            f"            <UML:DiagramElement geometry=\"SX=0;SY=0;EX=0;EY=0;EDGE=2;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;Path=;\" subject=\"{rel.rel_id}\" style=\"Mode=3;EOID=;SOID=;Color=-1;LWidth=0;Hidden=0;\"/>"
        )

    lines.append("          </UML:Diagram.element>")
    lines.append("        </UML:Diagram>")
    return lines


def _layout_elements(elements: List[Element]) -> Dict[str, Tuple[int, int, int, int]]:
    actors = [e for e in elements if e.element_type.lower() == "actor"]
    usecases = [e for e in elements if e.element_type.lower() != "actor"]

    layout: Dict[str, Tuple[int, int, int, int]] = {}

    # Actors on the left
    x_actor = 60
    y = 60
    for el in actors:
        layout[el.element_id] = (x_actor, y, x_actor + 60, y + 90)
        y += 120

    # Use cases in a grid to the right
    x0 = 240
    y0 = 60
    w = 220
    h = 120
    col = 0
    row = 0
    for el in usecases:
        left = x0 + col * (w + 40)
        top = y0 + row * (h + 40)
        layout[el.element_id] = (left, top, left + w, top + h)
        col += 1
        if col >= 2:
            col = 0
            row += 1

    return layout


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _eaid() -> str:
    u = _uuid_parts()
    return f"EAID_{u}"


def _eapk_id() -> str:
    u = _uuid_parts()
    return f"EAPK_{u}"


def _mx_id() -> str:
    u = _uuid_parts()
    return f"MX_EAID_{u}"


def _uuid_parts() -> str:
    u = uuid.uuid4().hex.upper()
    return f"{u[0:8]}_{u[8:12]}_{u[12:16]}_{u[16:20]}_{u[20:32]}"


def _duid() -> str:
    return uuid.uuid4().hex.upper()[0:8]
