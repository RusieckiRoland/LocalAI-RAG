# utils/step_overrides.py
from __future__ import annotations

from typing import Any, Mapping, Optional


def opt_int(v: object) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    return int(s)


def opt_float(v: object) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    s = str(v or "").strip()
    if not s:
        return None
    return float(s)


def get_override(*, raw: Mapping[str, Any], settings: Mapping[str, Any], key: str) -> Any:
    """
    Step-level value wins if present (even if None is explicitly set).
    """
    if key in raw:
        return raw.get(key)
    return settings.get(key)
