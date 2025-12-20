# code_query_engine/tools/pipeline_to_puml.py
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from code_query_engine.pipeline.loader import PipelineLoader
from code_query_engine.pipeline.definitions import PipelineDef, StepDef


def _safe_alias(step_id: str) -> str:
    """
    PlantUML alias must be simple; step_id may contain '/', '-', etc.
    We keep a deterministic alias.
    """
    # keep only alnum and underscore
    out = []
    for ch in step_id:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    alias = "".join(out).strip("_")
    if not alias:
        alias = "step"
    return f"s_{alias}"


def _extract_edges(step: StepDef) -> List[Tuple[str, str]]:
    """
    Returns list of (label, target_step_id).
    Deterministic rules:
    - if raw['next'] is str => edge label "next"
    - any raw keys starting with 'on_' where value is str => edge label is key[3:]
    """
    edges: List[Tuple[str, str]] = []

    raw = step.raw or {}

    nxt = raw.get("next")
    if isinstance(nxt, str) and nxt.strip():
        edges.append(("next", nxt.strip()))

    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if not k.startswith("on_"):
            continue
        if isinstance(v, str) and v.strip():
            edges.append((k[3:], v.strip()))

    return edges


def pipeline_to_puml(pipeline: PipelineDef) -> str:
    steps_by_id = pipeline.steps_by_id()

    # Nodes: (alias, label)
    nodes: List[Tuple[str, str]] = []
    for s in pipeline.steps:
        alias = _safe_alias(s.id)
        label = f"{s.id}\\n({s.action})"
        nodes.append((alias, label))

    # Edges: (src_alias, dst_alias, label)
    edges: List[Tuple[str, str, str]] = []
    for s in pipeline.steps:
        if s.end:
            continue
        for lbl, target_id in _extract_edges(s):
            if target_id not in steps_by_id:
                # Keep diagram generation robust; validator should catch this,
                # but we don't want diagram generation to crash.
                continue
            src = _safe_alias(s.id)
            dst = _safe_alias(target_id)
            edges.append((src, dst, lbl))

    entry = (pipeline.settings or {}).get("entry_step_id")
    entry = entry.strip() if isinstance(entry, str) else None
    entry_alias = _safe_alias(entry) if entry else None

    lines: List[str] = []
    lines.append("@startuml")
    lines.append("hide empty description")
    lines.append("skinparam monochrome true")
    lines.append("left to right direction")
    lines.append("")
    lines.append(f"title Pipeline: {pipeline.name}")
    lines.append("")

    # Node declarations
    for alias, label in nodes:
        lines.append(f'state "{label}" as {alias}')

    lines.append("")

    # Start marker
    if entry_alias and entry in steps_by_id:
        lines.append(f"[*] --> {entry_alias} : entry_step_id")

    # Edges
    for src, dst, lbl in edges:
        if lbl == "next":
            lines.append(f"{src} --> {dst}")
        else:
            lines.append(f"{src} --> {dst} : {lbl}")

    lines.append("@enduml")
    lines.append("")
    return "\n".join(lines)


def _load_pipeline(pipelines_root: str, pipeline_path: str) -> PipelineDef:
    loader = PipelineLoader(pipelines_root=pipelines_root)
    return loader.load_from_path(pipeline_path)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline_to_puml",
        description="Generate PlantUML diagram (.puml) from a YAML pipeline (supports extends merge).",
    )
    ap.add_argument(
        "pipeline",
        help="Path to YAML pipeline file (can use extends).",
    )
    ap.add_argument(
        "--pipelines-root",
        default="pipelines",
        help="Root directory for pipelines (used to resolve relative extends). Default: pipelines",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Output .puml file path. Default: <pipeline_filename>.puml next to the YAML.",
    )

    args = ap.parse_args()

    pipeline_path = str(Path(args.pipeline))
    pipe = _load_pipeline(args.pipelines_root, pipeline_path)

    puml = pipeline_to_puml(pipe)

    out_path = args.out
    if not out_path:
        p = Path(pipeline_path)
        out_path = str(p.with_suffix(".puml"))

    Path(out_path).write_text(puml, encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
