# code_query_engine/pipeline/lockfile.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .definitions import PipelineDef


ALLOWED_COMPAT_MODES = {"locked", "latest", "strict"}
LOCKFILE_VERSION = 1


_ACTION_DEFAULTS: Dict[str, Dict[str, Any]] = {
    # Pin behavioral defaults that are implicit in code today.
    # These are intentionally minimal and can be expanded as needed.
    "search_nodes": {
        "rerank": "none",
        "snapshot_source": "primary",
    },
    "inbox_dispatcher": {
        "directives_key": "dispatch",
    },
}


_COMMON_ALLOWED_KEYS = {
    "id",
    "action",
    "next",
    "end",
    "stages_visible",
    "callback_caption",
    "callback_caption_translated",
}


@dataclass(frozen=True)
class Lockfile:
    lock_version: int
    pipeline_name: str
    behavior_version: str
    actions: Dict[str, Dict[str, Any]]


def lockfile_path_for_yaml(yaml_path: Path) -> Path:
    return yaml_path.with_suffix(".lock.json")


def _sorted_list(values: Iterable[str]) -> List[str]:
    return sorted({str(v) for v in values if str(v).strip()})


def generate_lockfile(pipeline: PipelineDef) -> Lockfile:
    settings = pipeline.settings or {}
    behavior_version = str(settings.get("behavior_version") or "").strip()
    if not behavior_version:
        raise ValueError("pipeline.settings.behavior_version is required to generate lockfile")

    actions: Dict[str, Dict[str, Any]] = {}

    for step in pipeline.steps:
        action_id = str(step.action or "").strip()
        if not action_id:
            continue

        entry = actions.get(action_id)
        if entry is None:
            entry = {
                "behavior": behavior_version,
                "defaults": dict(_ACTION_DEFAULTS.get(action_id) or {}),
                "allowed_keys": set(_COMMON_ALLOWED_KEYS),
            }
            actions[action_id] = entry

        allowed_keys = entry.get("allowed_keys")
        if isinstance(allowed_keys, set):
            allowed_keys.update(step.raw.keys())

    # Normalize allowed_keys to sorted lists
    for entry in actions.values():
        allowed_keys = entry.get("allowed_keys")
        if isinstance(allowed_keys, set):
            entry["allowed_keys"] = _sorted_list(allowed_keys)

    return Lockfile(
        lock_version=LOCKFILE_VERSION,
        pipeline_name=pipeline.name,
        behavior_version=behavior_version,
        actions=actions,
    )


def serialize_lockfile(lockfile: Lockfile) -> Dict[str, Any]:
    return {
        "lock_version": int(lockfile.lock_version),
        "pipeline_name": str(lockfile.pipeline_name),
        "behavior_version": str(lockfile.behavior_version),
        "actions": lockfile.actions,
    }


def write_lockfile(*, lockfile: Lockfile, path: Path) -> None:
    data = serialize_lockfile(lockfile)
    txt = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(txt + "\n", encoding="utf-8")


def load_lockfile(path: Path) -> Lockfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("lockfile must be a JSON object")

    lock_version = int(raw.get("lock_version") or 0)
    if lock_version != LOCKFILE_VERSION:
        raise ValueError(f"lockfile.lock_version must be {LOCKFILE_VERSION}")

    pipeline_name = str(raw.get("pipeline_name") or "").strip()
    if not pipeline_name:
        raise ValueError("lockfile.pipeline_name is required")

    behavior_version = str(raw.get("behavior_version") or "").strip()
    if not behavior_version:
        raise ValueError("lockfile.behavior_version is required")

    actions = raw.get("actions")
    if not isinstance(actions, dict) or not actions:
        raise ValueError("lockfile.actions must be a non-empty object")

    # Validate action entries
    clean_actions: Dict[str, Dict[str, Any]] = {}
    for k, v in actions.items():
        action_id = str(k or "").strip()
        if not action_id or not isinstance(v, dict):
            continue
        behavior = str(v.get("behavior") or "").strip()
        if not behavior:
            raise ValueError(f"lockfile.actions['{action_id}'].behavior is required")
        defaults = v.get("defaults")
        if defaults is None:
            defaults = {}
        if not isinstance(defaults, dict):
            raise ValueError(f"lockfile.actions['{action_id}'].defaults must be an object")
        allowed_keys = v.get("allowed_keys")
        if allowed_keys is not None and not isinstance(allowed_keys, list):
            raise ValueError(f"lockfile.actions['{action_id}'].allowed_keys must be a list")
        clean_actions[action_id] = {
            "behavior": behavior,
            "defaults": defaults,
            "allowed_keys": allowed_keys or None,
        }

    if not clean_actions:
        raise ValueError("lockfile.actions must contain at least one valid action entry")

    return Lockfile(
        lock_version=lock_version,
        pipeline_name=pipeline_name,
        behavior_version=behavior_version,
        actions=clean_actions,
    )


def apply_lockfile(pipeline: PipelineDef, lockfile: Lockfile) -> PipelineDef:
    actions = lockfile.actions or {}

    new_steps = []
    for step in pipeline.steps:
        action_id = str(step.action or "").strip()
        entry = actions.get(action_id)
        if entry is None:
            raise ValueError(f"lockfile missing action entry for '{action_id}'")

        allowed_keys = entry.get("allowed_keys")
        if isinstance(allowed_keys, list) and allowed_keys:
            unknown = set(step.raw.keys()) - {str(k) for k in allowed_keys}
            if unknown:
                bad = ", ".join(sorted(str(k) for k in unknown))
                raise ValueError(
                    f"step '{step.id}' has keys not allowed by lockfile for action '{action_id}': {bad}"
                )

        defaults = entry.get("defaults") or {}
        new_raw = dict(step.raw)
        if isinstance(defaults, dict):
            for k, v in defaults.items():
                if k not in new_raw:
                    new_raw[k] = v

        new_steps.append(type(step)(id=step.id, action=step.action, raw=new_raw))

    return PipelineDef(name=pipeline.name, settings=pipeline.settings, steps=new_steps)

