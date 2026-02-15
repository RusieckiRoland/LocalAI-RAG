from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set


_LOCK = threading.Lock()
_MAX_DEPTH = 6


def _env_truthy(name: str) -> bool:
    v = str(os.getenv(name, "") or "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def weaviate_query_log_enabled() -> bool:
    return _env_truthy("WEAVIATE_QUERY_LOG")


def _project_root() -> Path:
    # code_query_engine/...
    return Path(__file__).resolve().parents[1]


def weaviate_query_log_dir() -> Path:
    raw = str(os.getenv("WEAVIATE_QUERY_LOG_DIR", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _project_root() / "log" / "weaviate" / "out"


def _ts_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_jsonable(v: Any, *, _depth: int = 0, _seen: Optional[Set[int]] = None) -> Any:
    """
    Best-effort conversion to JSON-serializable values.

    Requirements:
    - Must never raise (logging must not break the pipeline).
    - Must be reasonably stable and useful for reproducing Weaviate queries.
    - Must guard against recursion / huge objects.
    """
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v

    if _seen is None:
        _seen = set()
    if _depth >= _MAX_DEPTH:
        return repr(v)
    oid = id(v)
    if oid in _seen:
        return "<recursion>"
    _seen.add(oid)

    if isinstance(v, dict):
        out: Dict[str, Any] = {}
        for k, val in v.items():
            out[str(k)] = _safe_jsonable(val, _depth=_depth + 1, _seen=_seen)
        return out
    if isinstance(v, (list, tuple)):
        return [_safe_jsonable(x, _depth=_depth + 1, _seen=_seen) for x in v]

    # Common model / object encoders.
    for meth in ("model_dump", "to_dict", "_to_dict", "dict"):
        fn = getattr(v, meth, None)
        if callable(fn):
            try:
                return _safe_jsonable(fn(), _depth=_depth + 1, _seen=_seen)
            except Exception:
                pass
    fn = getattr(v, "to_json", None)
    if callable(fn):
        try:
            raw = fn()
            # Could be JSON string or already decoded.
            if isinstance(raw, str):
                return raw
            return _safe_jsonable(raw, _depth=_depth + 1, _seen=_seen)
        except Exception:
            pass

    # Weaviate filter objects show up as "<weaviate...filters._FilterAnd object at 0x...>".
    # They are critical for debugging timeouts, so we try hard to extract something structured.
    try:
        mod = str(getattr(v.__class__, "__module__", "") or "")
        name = str(getattr(v.__class__, "__name__", "") or "")
        if mod.startswith("weaviate."):
            # Prefer a few commonly present attributes on filter nodes.
            probe_keys = (
                "operator",
                "operands",
                "path",
                "property",
                "valueText",
                "valueTextArray",
                "valueBoolean",
                "valueInt",
                "valueNumber",
            )
            data: Dict[str, Any] = {"__type": f"{mod}.{name}"}
            for key in probe_keys:
                if hasattr(v, key):
                    try:
                        data[key] = _safe_jsonable(getattr(v, key), _depth=_depth + 1, _seen=_seen)
                    except Exception:
                        pass
            # Fallback: include a shallow vars() dump if available.
            try:
                d = vars(v)  # may fail for slots
            except Exception:
                d = None
            if isinstance(d, dict) and d:
                # Avoid giant payloads; keep a stable subset.
                for k in sorted(list(d.keys()))[:50]:
                    data[str(k)] = _safe_jsonable(d.get(k), _depth=_depth + 1, _seen=_seen)
            if len(data.keys()) > 1:
                return data
    except Exception:
        pass

    # Fallback: keep stable, avoid failing logging.
    return repr(v)


def _preview_200(v: Any) -> str:
    try:
        if isinstance(v, str):
            s = v
        else:
            s = json.dumps(_safe_jsonable(v), ensure_ascii=True)
    except Exception:
        s = repr(v)
    s = s.replace("\n", "\\n")
    return s[:200]


def log_weaviate_query(
    *,
    op: str,
    request: Dict[str, Any],
    response: Any = None,
    error: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """
    JSONL logger for Weaviate calls.

    Controlled by env:
    - WEAVIATE_QUERY_LOG=1 enables logging
    - WEAVIATE_QUERY_LOG_DIR overrides output directory (default: log/weaviate/out)

    Output: log/weaviate/out/weaviate_queries_YYYY-MM-DD.jsonl
    """
    if not weaviate_query_log_enabled():
        return

    out_dir = weaviate_query_log_dir()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Logging must never break the pipeline.
        return

    day = datetime.now(timezone.utc).date().isoformat()
    path = out_dir / f"weaviate_queries_{day}.jsonl"

    entry = {
        "ts_utc": _ts_utc(),
        "op": str(op or "").strip() or "unknown",
        "request": _safe_jsonable(request or {}),
        "response_preview": _preview_200(response),
        "error": (str(error) if error else None),
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "pid": os.getpid(),
    }

    line = json.dumps(entry, ensure_ascii=True, separators=(",", ":"))
    with _LOCK:
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            return


class _WeaviateCallTimer:
    def __init__(self) -> None:
        self._t0 = time.time()

    def ms(self) -> int:
        return int((time.time() - self._t0) * 1000)
