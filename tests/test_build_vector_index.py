# File: vector_db/build_vector_index.py
from __future__ import annotations

import json
import os
from typing import Dict, Optional
import zipfile


def load_config(
    script_dir: Optional[str] = None,
    config_path: Optional[str] = None
) -> tuple[Dict[str, str], str]:
    """
    Load config.json with optional path override.
    """
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg, os.path.dirname(config_path)

    script_dir = script_dir or os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "config.json"),
        os.path.join(os.path.dirname(script_dir), "config.json"),
    ]

    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg, os.path.dirname(path)

    print("ERROR: config.json not found.", file=sys.stderr)
    raise SystemExit(1)


def resolve_path(path: str, base_dir: str) -> str:
    """
    Resolve relative path against base directory.
    """
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


def top_level_in_zip(zip_path: str) -> str:
    """
    Return top-level folder in ZIP, excluding __MACOSX.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
    except Exception:
        names = []

    if not names:
        return os.path.splitext(os.path.basename(zip_path))[0]

    first_segments = {
        name.strip("/").split("/", 1)[0]
        for name in names
        if "/" in name and not name.strip("/").startswith("__MACOSX")
    }

    return next(iter(first_segments)) if len(first_segments) == 1 else os.path.splitext(os.path.basename(zip_path))[0]