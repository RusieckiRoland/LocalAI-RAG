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


def llm_query_log_enabled() -> bool:
    return _env_truthy("LLM_QUERY_LOG")


def _project_root() -> Path:
    # code_query_engine/...
    return Path(__file__).resolve().parents[1]


def llm_query_log_dir() -> Path:
    raw = str(os.getenv("LLM_QUERY_LOG_DIR", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _project_root() / "log" / "llm" / "out"


def _ts_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_jsonable(v: Any, *, _depth: int = 0, _seen: Optional[Set[int]] = None) -> Any:
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
            if isinstance(raw, str):
                return raw
            return _safe_jsonable(raw, _depth=_depth + 1, _seen=_seen)
        except Exception:
            pass

    return repr(v)


def log_llm_query(
    *,
    op: str,
    request: Dict[str, Any],
    response: Any = None,
    error: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """
    JSONL logger for LLM calls.

    Controlled by env:
    - LLM_QUERY_LOG=1 enables logging
    - LLM_QUERY_LOG_DIR overrides output directory (default: log/llm/out)

    Output: log/llm/out/llm_queries_YYYY-MM-DD.jsonl
    """
    if not llm_query_log_enabled():
        return

    out_dir = llm_query_log_dir()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    day = datetime.now(timezone.utc).date().isoformat()
    path = out_dir / f"llm_queries_{day}.jsonl"

    entry = {
        "ts_utc": _ts_utc(),
        "op": str(op or "").strip() or "unknown",
        "request": _safe_jsonable(request or {}),
        "response": _safe_jsonable(response),
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


class LLMCallTimer:
    def __init__(self) -> None:
        self._t0 = time.time()

    def ms(self) -> int:
        return int((time.time() - self._t0) * 1000)
