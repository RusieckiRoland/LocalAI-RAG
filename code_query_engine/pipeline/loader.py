# code_query_engine/pipeline/loader.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .definitions import PipelineDef, parse_pipeline_doc


def _deep_merge(parent: Any, child: Any) -> Any:
    """
    Deep-merge two YAML objects.

    Rules:
    - dict: merged recursively
    - list: overridden by child (except handled explicitly for 'steps')
    - scalar: overridden by child
    """
    if isinstance(parent, dict) and isinstance(child, dict):
        out: Dict[str, Any] = dict(parent)
        for k, v in child.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out

    # default: child overrides parent
    return child


def _merge_steps_by_id(parent_steps: List[Dict[str, Any]], child_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge step lists by 'id':
    - parent order preserved
    - if child contains step with same id -> deep-merge parent step with child step
    - new child steps appended in their order
    """
    def _by_id(steps: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for s in steps or []:
            if isinstance(s, dict) and s.get("id"):
                out[str(s["id"])] = s
        return out

    parent_steps = [s for s in (parent_steps or []) if isinstance(s, dict)]
    child_steps = [s for s in (child_steps or []) if isinstance(s, dict)]

    child_map = _by_id(child_steps)
    parent_map = _by_id(parent_steps)

    used: set[str] = set()
    out: List[Dict[str, Any]] = []

    # Preserve parent order
    for ps in parent_steps:
        sid = ps.get("id")
        if sid and str(sid) in child_map:
            out.append(_deep_merge(ps, child_map[str(sid)]))
            used.add(str(sid))
        else:
            out.append(ps)

    # Append new child steps
    for cs in child_steps:
        sid = cs.get("id")
        if not sid:
            continue
        sid_s = str(sid)
        if sid_s in used:
            continue
        if sid_s in parent_map:
            continue
        out.append(cs)

    return out


def _merge_pipeline_docs(parent_doc: Dict[str, Any], child_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge two documents shaped like:
      {"YAMLpipeline": {"name":..., "settings":..., "steps":[...], ...}}
    """
    parent = dict(parent_doc or {})
    child = dict(child_doc or {})

    pp = dict(parent.get("YAMLpipeline") or {})
    cp = dict(child.get("YAMLpipeline") or {})

    out_pipeline: Dict[str, Any] = _deep_merge(pp, cp)

    # Special-case: steps merged by id
    parent_steps = pp.get("steps") if isinstance(pp.get("steps"), list) else []
    child_steps = cp.get("steps") if isinstance(cp.get("steps"), list) else []
    if parent_steps or child_steps:
        out_pipeline["steps"] = _merge_steps_by_id(parent_steps, child_steps)

    return {"YAMLpipeline": out_pipeline}


def _parse_extends_value(value: str) -> Tuple[str, Optional[str]]:
    """
    Supports:
      extends: "base.yaml"
      extends: "base.yaml#pipeline_name"
    """
    v = (value or "").strip()
    if "#" in v:
        path_part, name_part = v.split("#", 1)
        path_part = path_part.strip()
        name_part = name_part.strip() or None
        return path_part, name_part
    return v, None


def _extract_pipelines_container(doc: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """
    Multi-pipeline formats supported (top-level):
      YAMLpipelines: [ {name, settings, steps, ...}, ... ]
      pipelines:     [ {name, settings, steps, ...}, ... ]   (alias)
    """
    if not isinstance(doc, dict):
        return None

    if isinstance(doc.get("YAMLpipelines"), list):
        return [x for x in doc["YAMLpipelines"] if isinstance(x, dict)]

    if isinstance(doc.get("pipelines"), list):
        return [x for x in doc["pipelines"] if isinstance(x, dict)]

    return None


def _select_pipeline_from_doc(doc: Dict[str, Any], *, pipeline_name: Optional[str]) -> Dict[str, Any]:
    """
    Returns a normalized single-pipeline doc: {"YAMLpipeline": {...}}.

    Supports:
      - single pipeline file: {"YAMLpipeline": {...}}
      - multi pipeline file: {"YAMLpipelines": [ {...}, {...} ]} (or "pipelines")
    """
    if not isinstance(doc, dict):
        raise ValueError("Pipeline YAML document must be a mapping (dict).")

    # Single pipeline
    if isinstance(doc.get("YAMLpipeline"), dict):
        return {"YAMLpipeline": dict(doc["YAMLpipeline"])}

    # Multi pipeline
    items = _extract_pipelines_container(doc)
    if items is None:
        raise ValueError("Invalid pipeline YAML: expected 'YAMLpipeline' or 'YAMLpipelines'/'pipelines'.")

    if not items:
        raise ValueError("Invalid pipeline YAML: pipelines list is empty.")

    if pipeline_name:
        for p in items:
            if str(p.get("name") or "").strip() == pipeline_name:
                return {"YAMLpipeline": dict(p)}
        raise KeyError(f"Pipeline '{pipeline_name}' not found in multi-pipeline file.")

    if len(items) == 1:
        return {"YAMLpipeline": dict(items[0])}

    raise ValueError("Multi-pipeline file requires pipeline_name (more than one pipeline present).")


@dataclass(frozen=True)
class _IndexedPipeline:
    file_path: Path
    pipeline_name: str


class PipelineLoader:
    """
    Pipeline loader.

    Backward compatible:
      - one file = one pipeline:
          YAMLpipeline: {name, settings, steps}

    New:
      - one file can contain many pipelines:
          YAMLpipelines:
            - name: p1
              settings: ...
              steps: ...
            - name: p2
              settings: ...
              steps: ...

        (alias: 'pipelines' instead of 'YAMLpipelines')
    """

    def __init__(self, *, pipelines_root: str) -> None:
        self._pipelines_root = Path(pipelines_root)
        self._index: Optional[Dict[str, _IndexedPipeline]] = None

    def load_by_name(self, name: str) -> PipelineDef:
        """
        Loads pipeline by its logical name.

        Resolution order:
        1) <pipelines_root>/<name>.yaml / .yml
           - if file is single -> use it
           - if file is multi -> select pipeline with matching name
        2) scan all *.yml/*.yaml under pipelines_root and find pipeline by 'name'
        """
        pipeline_name = (name or "").strip()
        if not pipeline_name:
            raise ValueError("Pipeline name cannot be empty.")

        direct = self._try_direct_file_by_name(pipeline_name)
        if direct is not None:
            path, selected_name = direct
            return self.load_from_path(str(path), pipeline_name=selected_name)

        idx = self._get_or_build_index()
        if pipeline_name not in idx:
            raise FileNotFoundError(f"Pipeline '{pipeline_name}' not found under '{self._pipelines_root}'.")
        info = idx[pipeline_name]
        return self.load_from_path(str(info.file_path), pipeline_name=info.pipeline_name)

    def list_pipeline_names(self) -> List[str]:
        """
        Returns all known pipeline names under pipelines_root.
        """
        idx = self._get_or_build_index()
        return sorted(idx.keys())

    def load_from_path(self, path: str, *, pipeline_name: Optional[str] = None) -> PipelineDef:
        p = Path(path)
        doc = self._load_doc_with_extends(path=p, pipeline_name=pipeline_name, depth=0)
        return parse_pipeline_doc(doc)

    # ------------------------- #
    # Internals
    # ------------------------- #

    def _try_direct_file_by_name(self, pipeline_name: str) -> Optional[Tuple[Path, Optional[str]]]:
        for ext in (".yaml", ".yml"):
            p = self._pipelines_root / f"{pipeline_name}{ext}"
            if p.exists() and p.is_file():
                # file name matches pipeline name; if file is multi it can still contain many pipelines,
                # but we select by the logical name.
                return p, pipeline_name
        return None

    def _get_or_build_index(self) -> Dict[str, _IndexedPipeline]:
        if self._index is not None:
            return self._index

        idx: Dict[str, _IndexedPipeline] = {}
        if not self._pipelines_root.exists():
            self._index = idx
            return idx

        for path in sorted(self._pipelines_root.rglob("*.yml")) + sorted(self._pipelines_root.rglob("*.yaml")):
            if not path.is_file():
                continue
            try:
                raw = self._read_yaml(path)
            except Exception:
                continue

            # Single pipeline
            if isinstance(raw, dict) and isinstance(raw.get("YAMLpipeline"), dict):
                n = str(raw["YAMLpipeline"].get("name") or "").strip()
                if n:
                    if n in idx and idx[n].file_path != path:
                        raise ValueError(f"Duplicate pipeline name '{n}' found in: {idx[n].file_path} and {path}")
                    idx[n] = _IndexedPipeline(file_path=path, pipeline_name=n)
                continue

            # Multi pipeline
            items = _extract_pipelines_container(raw) if isinstance(raw, dict) else None
            if items:
                for p in items:
                    n = str(p.get("name") or "").strip()
                    if not n:
                        continue
                    if n in idx and idx[n].file_path != path:
                        raise ValueError(f"Duplicate pipeline name '{n}' found in: {idx[n].file_path} and {path}")
                    idx[n] = _IndexedPipeline(file_path=path, pipeline_name=n)

        self._index = idx
        return idx

    def _load_doc_with_extends(self, *, path: Path, pipeline_name: Optional[str], depth: int) -> Dict[str, Any]:
        if depth > 20:
            raise ValueError("Too deep extends chain (possible cycle).")

        raw = self._read_yaml(path)
        doc = _select_pipeline_from_doc(raw, pipeline_name=pipeline_name)

        pipeline = dict(doc.get("YAMLpipeline") or {})
        extends_val = pipeline.get("extends")
        if not extends_val:
            return doc

        target_raw, extends_pipeline_name = _parse_extends_value(str(extends_val))
        parent_path = self._normalize_extends_target(current_path=path, target=target_raw)

        parent_doc = self._load_doc_with_extends(
            path=parent_path,
            pipeline_name=extends_pipeline_name,
            depth=depth + 1,
        )

        # Child overrides parent; keep child's own name unless it is missing.
        merged = _merge_pipeline_docs(parent_doc, doc)

        # Ensure child name wins if present
        child_name = (doc.get("YAMLpipeline") or {}).get("name")
        if child_name:
            merged["YAMLpipeline"]["name"] = child_name

        # Child extends should not leak after merge
        merged["YAMLpipeline"].pop("extends", None)

        return merged

    def _normalize_extends_target(self, *, current_path: Path, target: str) -> Path:
        """
        Extends target can be:
        - absolute path
        - relative path (resolved against current file directory)
        - pipeline name file (resolved under pipelines_root)
        """
        t = (target or "").strip()
        if not t:
            raise ValueError("extends target cannot be empty.")

        candidate = Path(t)
        if candidate.is_absolute():
            return candidate

        # 1) relative to current file
        rel = (current_path.parent / candidate).resolve()
        if rel.exists() and rel.is_file():
            return rel

        # 2) under pipelines_root
        under_root = (self._pipelines_root / candidate).resolve()
        if under_root.exists() and under_root.is_file():
            return under_root

        # 3) allow extends: "base" (auto add .yaml/.yml)
        for ext in (".yaml", ".yml"):
            under_root2 = (self._pipelines_root / f"{t}{ext}").resolve()
            if under_root2.exists() and under_root2.is_file():
                return under_root2

        raise FileNotFoundError(f"extends target not found: '{target}' (from: {current_path})")

    def _read_yaml(self, path: Path) -> Dict[str, Any]:
        txt = path.read_text(encoding="utf-8")
        data = yaml.safe_load(txt)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"Pipeline YAML must be a mapping (dict). Got: {type(data).__name__}")
        return data
