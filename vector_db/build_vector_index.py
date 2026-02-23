from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple


def load_config(
    script_dir: Optional[str] = None,
    config_path: Optional[str] = None
) -> tuple[Dict[str, str], str]:
    """
    Load config.json with optional path override.

    Resolution order (deterministic):
      1) explicit config_path (if provided)
      2) tests/config.json when running under pytest (if present)
      3) vector_db/config.json
      4) repo_root/config.json
      5) <cwd>/config.json

    Returns: (cfg, config_dir) where config_dir is the directory containing the chosen config file.
    """
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg, os.path.dirname(config_path)

    script_dir = script_dir or os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)

    # Auto-detect pytest without any user-provided flags/env-vars.
    is_pytest = ("PYTEST_CURRENT_TEST" in os.environ) or ("pytest" in sys.modules)

    candidates: list[str] = []

    test_config = os.path.join(repo_root, "tests", "config.json")
    if is_pytest and os.path.isfile(test_config):
        candidates.append(test_config)

    candidates.extend([
        os.path.join(script_dir, "config.json"),
        os.path.join(repo_root, "config.json"),
        os.path.join(os.getcwd(), "config.json"),
    ])

    # Deduplicate while preserving order
    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)

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
    Extract ZIP into branches/<BranchName> and return absolute path to that folder.

    IMPORTANT (target layout):
      branches/<BranchName>/...

    BranchName is ALWAYS derived from the ZIP filename stem (e.g. Release_4.60.zip -> Release_4.60),
    regardless of how the ZIP is structured inside.

    Supported ZIP layouts:
    - Flat (regular_code_bundle/... at top-level) -> moved under branches/<BranchName>/
    - Nested single root (SomeFolder/regular_code_bundle/...) -> flattened into branches/<BranchName>/
    """
    branches_dir_p = Path(branches_dir)
    branches_dir_p.mkdir(parents=True, exist_ok=True)

    branch_name = Path(zip_path).stem
    out_root = branches_dir_p / branch_name

    # Deterministic and safe: always overwrite the branch root on every run.
    # Reusing an existing folder silently mixes old/new bundles and breaks branch isolation.
    if out_root.exists():
        if out_root.is_dir():
            shutil.rmtree(out_root, ignore_errors=True)
        else:
            out_root.unlink(missing_ok=True)

    tmp_root = branches_dir_p / f".__extract_tmp__{branch_name}"
    if tmp_root.exists():
        shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(str(tmp_root))

        # If the ZIP had a single top-level directory, flatten it
        entries = [p for p in tmp_root.iterdir() if p.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir():
            extracted_root = entries[0]
        else:
            extracted_root = tmp_root

        out_root.mkdir(parents=True, exist_ok=True)

        # Move all extracted content under branches/<BranchName>/
        for item in extracted_root.iterdir():
            if item.name == "__MACOSX":
                continue
            dest = out_root / item.name
            if dest.exists():
                # Should not happen normally; keep deterministic by removing the destination.
                if dest.is_dir():
                    shutil.rmtree(dest, ignore_errors=True)
                else:
                    dest.unlink(missing_ok=True)
            shutil.move(str(item), str(dest))

        return str(out_root.resolve())
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _top_level_in_zip(zip_path: str) -> str:
    """
    Kept for backward compatibility; no longer used for naming, only for diagnostics if needed.
    """
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
