# code_query_engine/pipeline/loader.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import yaml

from .definitions import PipelineDef, parse_pipeline_doc


def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep-merge mappings:
    - dict + dict => recursive merge
    - otherwise => b overwrites a
    Lists are overwritten (not concatenated).
    """
    out = dict(a)
    for k, vb in b.items():
        va = out.get(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            out[k] = _deep_merge(va, vb)
        else:
            out[k] = vb
    return out


def _merge_steps_by_id(parent_steps: List[Dict[str, Any]], child_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge steps by `id`:
    - new id => append
    - same id => override whole step definition
    Keeps parent order, appends new child steps in child order.
    """
    out: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}

    for s in parent_steps:
        sid = s.get("id")
        if sid in index:
            continue
        index[sid] = len(out)
        out.append(s)

    for s in child_steps:
        sid = s.get("id")
        if sid in index:
            out[index[sid]] = s
        else:
            index[sid] = len(out)
            out.append(s)

    return out


def _normalize_extends_target(
    extends_value: str,
    *,
    current_file_dir: str,
    pipelines_root: str,
) -> str:
    """
    Supports:
    - relative paths: ./../base/foo or ./base/foo
    - bare names: marian_rejewski_code_analysis_base
      -> tries {pipelines_root}/{name}.yaml then {pipelines_root}/base/{name}.yaml
    Also auto-adds ".yaml" if missing.
    """
    raw = (extends_value or "").strip()
    if not raw:
        raise ValueError("extends is empty.")

    def _with_yaml(p: str) -> str:
        return p if os.path.splitext(p)[1].lower() in (".yaml", ".yml") else (p + ".yaml")

    has_pathish = ("/" in raw) or ("\\" in raw) or raw.startswith(".")
    if has_pathish:
        candidate = raw
        if not os.path.isabs(candidate):
            candidate = os.path.normpath(os.path.join(current_file_dir, candidate))
        candidate = _with_yaml(candidate)
        return candidate

    # Bare name: try pipelines_root/name.yaml then pipelines_root/base/name.yaml
    c1 = _with_yaml(os.path.join(pipelines_root, raw))
    if os.path.isfile(c1):
        return c1

    c2 = _with_yaml(os.path.join(pipelines_root, "base", raw))
    return c2


class PipelineLoader:
    """
    Loads YAMLpipeline docs with optional inheritance (extends).
    Merge rules:
    - settings: deep-merge (child overrides)
    - steps: merge by id (new add, same override whole step)
    """

    def __init__(self, pipelines_root: str) -> None:
        self.pipelines_root = os.path.abspath(pipelines_root)

    def load_from_path(self, path: str) -> PipelineDef:
        path = os.path.abspath(path)
        doc = self._load_doc_with_extends(path, seen=[])
        return parse_pipeline_doc(doc)

    def load_by_name(self, name: str) -> PipelineDef:
        name = (name or "").strip()
        if not name:
            raise ValueError("Pipeline name is empty.")
        file_name = name if name.endswith(".yaml") or name.endswith(".yml") else f"{name}.yaml"
        path = os.path.join(self.pipelines_root, file_name)
        return self.load_from_path(path)

    def _read_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Pipeline YAML not found: {path}")
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        if not isinstance(doc, dict):
            raise ValueError(f"Invalid YAML (root must be mapping): {path}")
        return doc

    def _load_doc_with_extends(self, path: str, seen: List[str]) -> Dict[str, Any]:
        if path in seen:
            chain = " -> ".join(seen + [path])
            raise ValueError(f"extends cycle detected: {chain}")
        seen = seen + [path]

        child = self._read_yaml(path)
        root = child.get("YAMLpipeline") or {}
        if not isinstance(root, dict):
            raise ValueError(f"Invalid pipeline YAML (missing YAMLpipeline): {path}")

        extends_value = root.get("extends")
        if not extends_value:
            return child

        if not isinstance(extends_value, str):
            raise ValueError(f"Invalid extends (must be string) in: {path}")

        parent_path = _normalize_extends_target(
            extends_value,
            current_file_dir=os.path.dirname(path),
            pipelines_root=self.pipelines_root,
        )
        parent = self._load_doc_with_extends(parent_path, seen=seen)

        # Merge parent -> child at YAMLpipeline level
        parent_root = parent.get("YAMLpipeline") or {}
        child_root = child.get("YAMLpipeline") or {}

        if not isinstance(parent_root, dict) or not isinstance(child_root, dict):
            raise ValueError("Invalid YAMLpipeline root in extends merge.")

        merged_root: Dict[str, Any] = dict(parent_root)

        # settings deep merge
        parent_settings = parent_root.get("settings") or {}
        child_settings = child_root.get("settings") or {}
        if not isinstance(parent_settings, dict) or not isinstance(child_settings, dict):
            raise ValueError("settings must be mappings in pipeline YAML.")
        merged_root["settings"] = _deep_merge(parent_settings, child_settings)

        # steps merge by id
        parent_steps = parent_root.get("steps") or []
        child_steps = child_root.get("steps") or []
        if not isinstance(parent_steps, list) or not isinstance(child_steps, list):
            raise ValueError("steps must be lists in pipeline YAML.")
        merged_root["steps"] = _merge_steps_by_id(parent_steps, child_steps)

        # name: child overrides if present else parent
        merged_root["name"] = (child_root.get("name") or parent_root.get("name") or "").strip()

        # keep child's extends only for debugging (not used after merge)
        merged_root.pop("extends", None)

        return {"YAMLpipeline": merged_root}
