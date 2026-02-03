from __future__ import annotations

import json
import os
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TemplatesStore:
    """
    Loads UI templates from disk with a simple mtime cache.
    """
    candidates: List[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_lock", Lock())
        object.__setattr__(self, "_cache", {})  # type: ignore[attr-defined]

    def load(self) -> Dict[str, Any]:
        for path in self.candidates:
            if os.path.isfile(path):
                return self._load_json(path)
        return {}

    def _load_json(self, path: str) -> Dict[str, Any]:
        with self._lock:  # type: ignore[attr-defined]
            cache: Dict[str, Tuple[float, Dict[str, Any]]] = self._cache  # type: ignore[attr-defined]
            try:
                mtime = os.path.getmtime(path)
            except FileNotFoundError:
                return {}

            cached = cache.get(path)
            if cached and cached[0] == mtime:
                return cached[1]

            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

            cache[path] = (mtime, data)
            return data


def default_templates_store(project_root: str) -> TemplatesStore:
    return TemplatesStore(
        candidates=[
            os.path.join(project_root, "ui_contracts", "templates.json"),
            os.path.join(project_root, "ui_contracts", "frontend_requirements", "templates.json"),
        ]
    )
