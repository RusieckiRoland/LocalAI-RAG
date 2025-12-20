# vector_db/build_vector_index.py
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple


def load_config(
    script_dir: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Tuple[Dict[str, object], str]:
    """
    Load config.json. Returns (cfg, config_dir).
    """
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg, os.path.dirname(config_path)

    script_dir = script_dir or os.path.dirname(os.path.abspath(__file__))

    # Common locations: repo root, or one level up (depending on how scripts are invoked)
    candidates = [
        os.path.join(script_dir, "..", "config.json"),
        os.path.join(script_dir, "..", "..", "config.json"),
        os.path.join(os.getcwd(), "config.json"),
    ]

    for path in map(os.path.normpath, candidates):
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg, os.path.dirname(path)

    raise FileNotFoundError("config.json not found (checked script_dir/.., script_dir/../.., cwd)")


def resolve_path(path: str, base_dir: str) -> str:
    """
    Resolve relative path against base directory.
    """
    if not path:
        return os.path.normpath(base_dir)

    if os.path.isabs(path):
        return os.path.normpath(path)

    return os.path.normpath(os.path.join(base_dir, path))


def human_size(path_or_bytes: str | int) -> str:
    """
    Human readable size for file path or raw bytes.
    """
    if isinstance(path_or_bytes, int):
        size = int(path_or_bytes)
    else:
        try:
            size = int(os.path.getsize(path_or_bytes))
        except Exception:
            size = 0

    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(size)
    u = 0
    while v >= 1024.0 and u < len(units) - 1:
        v /= 1024.0
        u += 1

    if u == 0:
        return f"{int(v)} {units[u]}"
    return f"{v:.1f} {units[u]}"


def extract_to_named_root(zip_path: str, branches_dir: str) -> str:
    """
    Extract zip into branches_dir and return absolute path to extracted root folder.

    Expected ZIP layout: <root_folder>/...
    If multiple roots exist, fallback to zip filename (without extension).
    """
    branches_dir_p = Path(branches_dir)
    branches_dir_p.mkdir(parents=True, exist_ok=True)

    root_name = _top_level_in_zip(zip_path) or Path(zip_path).stem
    out_root = branches_dir_p / root_name

    # Deterministic: if already exists, reuse
    if out_root.is_dir():
        return str(out_root.resolve())

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(str(branches_dir_p))

    return str(out_root.resolve())


def _top_level_in_zip(zip_path: str) -> str:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = [n for n in zf.namelist() if n and not n.startswith("__MACOSX")]
    except Exception:
        return ""

    if not names:
        return ""

    top_levels = set()
    for n in names:
        n = n.strip("/")
        if not n:
            continue
        top_levels.add(n.split("/", 1)[0])

    if len(top_levels) == 1:
        return next(iter(top_levels))
    return ""
