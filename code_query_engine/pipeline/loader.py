# code_query_engine/pipeline/loader.py
from __future__ import annotations

import os
import yaml
from typing import Any, Dict, List, Optional

from .definitions import parse_pipeline_doc, PipelineDef


def _deep_merge(parent: Any, child: Any) -> Any:
    # Dict merge
    if isinstance(parent, dict) and isinstance(child, dict):
        merged = dict(parent)
        for k, v in child.items():
            if k in merged:
                merged[k] = _deep_merge(merged[k], v)
            else:
                merged[k] = v
        return merged
    # List merge: for YAMLpipeline.steps we override by id (handled separately)
    return child


def _merge_steps_by_id(parent_steps: List[Dict[str, Any]], child_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # child can override parent steps by id; new child steps are appended deterministically
    parent_by_id: Dict[str, Dict[str, Any]] = {s.get("id"): s for s in parent_steps if isinstance(s, dict) and s.get("id")}
    out: List[Dict[str, Any]] = []

    used = set()

    # preserve parent order
    for ps in parent_steps:
        sid = ps.get("id")
        if sid and sid in child_steps_by_id(child_steps):
            out.append(_deep_merge(ps, child_steps_by_id(child_steps)[sid]))
            used.add(sid)
        else:
            out.append(ps)

    # append new child steps (stable order)
    for cs in child_steps:
        sid = cs.get("id")
        if sid and sid not in used and sid not in parent_by_id:
            out.append(cs)

    return out


def child_steps_by_id(child_steps: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {s.get("id"): s for s in child_steps if isinstance(s, dict) and s.get("id")}


def _normalize_extends_target(extends_value: str, *, current_file_dir: str, pipelines_root: str) -> str:
    """
    Supports:
    - Bare names (e.g. "base") => pipelines_root/base.yaml
    - Relative paths (e.g. "common/base.yaml", "../x.yaml") => resolved from current file dir
    - Absolute paths => accepted (but will be guarded by caller unless test pipeline)
    """
    v = (extends_value or "").strip()
    if not v:
        raise ValueError("extends must be non-empty")

    # If user provided bare name, we assume it's in pipelines_root and add ".yaml"
    has_pathish = any(sep in v for sep in ("/", "\\"))
    if not has_pathish and not v.endswith(".yaml"):
        v = f"{v}.yaml"
        return os.path.join(pipelines_root, v)

    # Pathish: resolve relative to current file dir unless absolute.
    if os.path.isabs(v):
        return v

    # relative path from current YAML file
    candidate = os.path.normpath(os.path.join(current_file_dir, v))
    return candidate


class PipelineLoader:
    def __init__(self, *, pipelines_root: str) -> None:
        self.pipelines_root = os.path.abspath(os.fspath(pipelines_root))

    def load_from_path(self, path: str) -> PipelineDef:
        doc = self._load_doc_with_extends(path, seen=[])
        return parse_pipeline_doc(doc)

    def load_by_name(self, name: str) -> PipelineDef:
        name = (name or "").strip()
        if not name:
            raise ValueError("pipeline name is empty")

        file_name = name if name.endswith(".yaml") else f"{name}.yaml"
        path = os.path.join(self.pipelines_root, file_name)
        return self.load_from_path(path)

    def _load_doc_with_extends(self, path: str, *, seen: List[str]) -> Dict[str, Any]:
        path = os.path.abspath(os.fspath(path))

        if path in seen:
            chain = " -> ".join(seen + [path])
            raise ValueError(f"extends cycle detected: {chain}")

        seen = seen + [path]
        child = self._read_yaml(path)
        root = child.get("YAMLpipeline") or {}
        if not isinstance(root, dict):
            raise ValueError(f"YAMLpipeline must be mapping in: {path}")

        extends_value = root.get("extends")
        if not extends_value:
            return child

        settings = root.get("settings") or {}
        if not isinstance(settings, dict):
            raise ValueError(f"settings must be mapping in: {path}")
        is_test_pipeline = bool(settings.get("test"))

        parent_path = _normalize_extends_target(
            extends_value,
            current_file_dir=os.path.dirname(path),
            pipelines_root=self.pipelines_root,
        )

        if not is_test_pipeline:
            parent_abs = os.path.abspath(parent_path)
            root_abs = os.path.abspath(self.pipelines_root)
            try:
                common = os.path.commonpath([parent_abs, root_abs])
            except Exception:
                common = ""
            if common != root_abs:
                raise PermissionError(
                    f"extends target escapes pipelines_root (set settings.test=true to allow in tests): {parent_abs}"
                )

        parent_doc = self._load_doc_with_extends(parent_path, seen=seen)

        # Merge docs:
        # - Entire YAML file merges with deep-merge
        # - YAMLpipeline.steps merges by id
        merged = _deep_merge(parent_doc, child)

        p_root = (parent_doc.get("YAMLpipeline") or {})
        c_root = (child.get("YAMLpipeline") or {})
        p_steps = p_root.get("steps") or []
        c_steps = c_root.get("steps") or []

        if isinstance(p_steps, list) and isinstance(c_steps, list):
            merged.setdefault("YAMLpipeline", {})
            merged["YAMLpipeline"].setdefault("steps", [])
            merged["YAMLpipeline"]["steps"] = _merge_steps_by_id(p_steps, c_steps)

        return merged

    def _read_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Pipeline YAML not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}

        if not isinstance(doc, dict):
            raise ValueError(f"YAML root must be mapping: {path}")

        return doc
