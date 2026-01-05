# tools/debug_retrieval_probe.py
"""
Debug probe for "0 retrieval results" situations.

Goal
----
Print clear, English diagnostics about:
- whether index/metadata files exist,
- what values exist for filters like branch/repository/data_type,
- whether common entry-point files (Program.cs / Startup.cs) appear in metadata,
- whether anything BM25-related artifacts exist on disk.

This script does NOT modify anything. It only reads files and prints diagnostics.

Usage
-----
Run from your LocalAI-RAG repo root (or anywhere inside it):

    python tools/debug_retrieval_probe.py

Optional env overrides:
- CONFIG_JSON         -> explicit path to config.json
- PROMPTS_DIR         -> not used here, but kept consistent with other tooling
- INDEX_DIR           -> explicit path to the index directory (skips config)
- METADATA_FILE       -> explicit path to metadata file (skips auto-detect)
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# -----------------------------
# Small helpers
# -----------------------------

def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _try_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_safe_read_text(path))
    except Exception as ex:
        print(f"[WARN] Failed to parse JSON: {path} ({type(ex).__name__}: {ex})")
        return None


def _find_upwards(start: Path, filename: str, max_hops: int = 8) -> Optional[Path]:
    cur = start.resolve()
    for _ in range(max_hops):
        candidate = cur / filename
        if candidate.exists() and candidate.is_file():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _coalesce(*vals: Any) -> Any:
    for v in vals:
        if v is not None:
            return v
    return None


def _get_any(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d:
            return d.get(k)
    return None


def _normalize_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


# -----------------------------
# Config / index resolution
# -----------------------------

def resolve_config_path(cwd: Path) -> Optional[Path]:
    env = os.environ.get("CONFIG_JSON")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p
        print(f"[WARN] CONFIG_JSON is set but file does not exist: {p}")

    # Common: config.json next to repo root or above it.
    p = _find_upwards(cwd, "config.json", max_hops=12)
    return p


def extract_index_dir_from_config(cfg: Dict[str, Any], cfg_path: Path) -> Optional[Path]:
    """
    Best-effort: different projects name it differently.
    Add more keys here if your config uses a known field name.
    """
    # Candidate keys (adapt if your config uses other names)
    candidates = [
        ("paths", "index_dir"),
        ("paths", "active_index_dir"),
        ("paths", "vector_index_dir"),
        ("paths", "unified_index_dir"),
        ("index", "dir"),
        ("index_dir",),
        ("active_index_dir",),
    ]

    def get_nested(obj: Dict[str, Any], path: Tuple[str, ...]) -> Any:
        cur: Any = obj
        for k in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    for key_path in candidates:
        v = get_nested(cfg, key_path)
        if isinstance(v, str) and v.strip():
            # Interpret relative paths relative to config location.
            p = (cfg_path.parent / v).expanduser().resolve()
            return p

    return None


def resolve_index_dir(cwd: Path) -> Optional[Path]:
    env = os.environ.get("INDEX_DIR")
    if env:
        p = Path(env).expanduser().resolve()
        return p

    cfg_path = resolve_config_path(cwd)
    if not cfg_path:
        print("[WARN] Could not find config.json automatically.")
        return None

    cfg = _try_load_json(cfg_path)
    if not cfg:
        return None

    idx = extract_index_dir_from_config(cfg, cfg_path)
    return idx


def resolve_metadata_file(index_dir: Path) -> Optional[Path]:
    env = os.environ.get("METADATA_FILE")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p
        print(f"[WARN] METADATA_FILE is set but file does not exist: {p}")

    # Common candidates
    candidates = [
        index_dir / "unified_metadata.json",
        index_dir / "metadata.json",
        index_dir / "metadata.jsonl",
        index_dir / "unified_metadata.jsonl",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p

    # Fallback: scan for something metadata-ish
    for p in sorted(index_dir.glob("**/*metadata*.json*")):
        if p.is_file():
            return p

    return None


# -----------------------------
# Metadata parsing
# -----------------------------

def load_metadata_rows(metadata_path: Path, max_rows: int = 200_000) -> List[Dict[str, Any]]:
    """
    Supports:
    - JSON array of objects
    - JSON object with 'rows' / 'items' / 'data'
    - JSONL (one object per line)
    """
    text = _safe_read_text(metadata_path).strip()
    if not text:
        print(f"[WARN] Empty metadata file: {metadata_path}")
        return []

    rows: List[Dict[str, Any]] = []

    # JSONL: many lines starting with '{'
    if "\n" in text and text.lstrip().startswith("{") and not text.lstrip().startswith("["):
        # Could still be single JSON object; try JSON first.
        obj = _try_load_json(metadata_path)
        if isinstance(obj, dict):
            # Not JSONL, it's JSON object
            pass
        elif obj is None:
            # Fallback JSONL parse
            for i, line in enumerate(text.splitlines()):
                if i >= max_rows:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        rows.append(rec)
                except Exception:
                    continue
            return rows

    # Normal JSON parse
    obj = _try_load_json(metadata_path)
    if obj is None:
        # Try JSONL as last resort
        for i, line in enumerate(text.splitlines()):
            if i >= max_rows:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    rows.append(rec)
            except Exception:
                continue
        return rows

    if isinstance(obj, list):
        for rec in obj[:max_rows]:
            if isinstance(rec, dict):
                rows.append(rec)
        return rows

    if isinstance(obj, dict):
        container = _coalesce(
            obj.get("rows"),
            obj.get("items"),
            obj.get("data"),
            obj.get("documents"),
        )
        if isinstance(container, list):
            for rec in container[:max_rows]:
                if isinstance(rec, dict):
                    rows.append(rec)
        else:
            # A single record
            rows.append(obj)
        return rows

    return []


def summarize_unique(rows: List[Dict[str, Any]], key_candidates: List[str], top_n: int = 12) -> None:
    """
    Print unique values (top occurrences) for the first key that exists.
    """
    key_used = None
    for k in key_candidates:
        if any(k in r for r in rows):
            key_used = k
            break

    if not key_used:
        print(f"Key not found. Tried: {key_candidates}")
        return

    cnt = Counter(_normalize_str(r.get(key_used)) for r in rows if r.get(key_used) is not None)
    most = cnt.most_common(top_n)
    uniq = len(cnt)
    total = sum(cnt.values())

    print(f"Key: '{key_used}'  (unique={uniq}, total_with_key={total})")
    for v, n in most:
        print(f"  - {v!r}: {n}")


def find_path_hits(rows: List[Dict[str, Any]], needles: List[str], path_keys: List[str]) -> None:
    """
    Count occurrences of 'needles' in any of the candidate path keys.
    """
    # choose keys that actually exist
    existing_keys = [k for k in path_keys if any(k in r for r in rows)]
    if not existing_keys:
        print(f"No path-like keys found. Tried: {path_keys}")
        return

    hits = {needle: 0 for needle in needles}
    examples: Dict[str, List[str]] = {needle: [] for needle in needles}

    for r in rows:
        for k in existing_keys:
            v = r.get(k)
            if not isinstance(v, str) or not v:
                continue
            low = v.lower()
            for needle in needles:
                if needle.lower() in low:
                    hits[needle] += 1
                    if len(examples[needle]) < 3:
                        examples[needle].append(v)

    for needle in needles:
        print(f"{needle}: hits={hits[needle]}")
        for ex in examples[needle]:
            print(f"  example: {ex}")


def scan_bm25_artifacts(index_dir: Path) -> None:
    """
    Best-effort file scan. This does not guarantee BM25 is configured,
    but quickly tells you whether there are any bm25-ish artifacts.
    """
    patterns = [
        "*bm25*",
        "*BM25*",
    ]
    found: List[Path] = []
    for pat in patterns:
        found.extend([p for p in index_dir.glob(f"**/{pat}") if p.is_file()])

    # de-dup
    uniq = []
    seen = set()
    for p in found:
        s = str(p)
        if s not in seen:
            uniq.append(p)
            seen.add(s)

    print(f"BM25-ish artifacts found: {len(uniq)}")
    for p in uniq[:20]:
        print(f"  - {p}")


# -----------------------------
# Main
# -----------------------------

def main() -> None:
    cwd = Path.cwd()

    _print_header("Retrieval Probe: Resolve index directory")
    cfg_path = resolve_config_path(cwd)
    if cfg_path:
        print(f"config.json: {cfg_path}")
    else:
        print("config.json: NOT FOUND (you can set CONFIG_JSON=/path/to/config.json)")

    index_dir = resolve_index_dir(cwd)
    if not index_dir:
        print("index_dir: NOT RESOLVED (you can set INDEX_DIR=/path/to/index)")
        return

    print(f"index_dir: {index_dir}")
    if not index_dir.exists():
        print("[ERROR] index_dir does not exist on disk. That alone can explain 0 results.")
        return

    _print_header("Retrieval Probe: Resolve metadata file")
    meta_path = resolve_metadata_file(index_dir)
    if not meta_path:
        print("[ERROR] No metadata file found in index_dir.")
        print("Set METADATA_FILE=/path/to/metadata.json or metadata.jsonl if needed.")
        return

    print(f"metadata_file: {meta_path}")

    _print_header("Retrieval Probe: Load metadata rows")
    rows = load_metadata_rows(meta_path)
    print(f"rows_loaded: {len(rows)}")
    if not rows:
        print("[ERROR] Metadata rows are empty. That alone can explain 0 results.")
        return

    # Print a quick view of keys
    sample_keys = sorted(set().union(*(r.keys() for r in rows[:50])))
    print(f"sample_keys (from first 50 rows): {sample_keys}")

    _print_header("Retrieval Probe: Check filter value coverage (branch/repository/data_type)")
    print("BRANCH values:")
    summarize_unique(rows, ["branch", "git_branch", "branch_name", "index_branch"])
    print("\nREPOSITORY values:")
    summarize_unique(rows, ["repository", "repo", "repo_name", "index_repository"])
    print("\nDATA_TYPE values:")
    summarize_unique(rows, ["data_type", "datatype", "index_data_type", "kind"])

    _print_header("Retrieval Probe: Check whether entry point files appear in metadata paths")
    find_path_hits(
        rows,
        needles=["Program.cs", "Startup.cs"],
        path_keys=["path", "file_path", "relpath", "relative_path", "source_path", "file", "document_path"],
    )

    _print_header("Retrieval Probe: Quick BM25 artifact scan")
    scan_bm25_artifacts(index_dir)

    _print_header("Done")
    print(
        "If your pipeline query returns 0 results, the most common causes are:\n"
        "1) index_dir points to a different index than you think,\n"
        "2) filters (branch/repository/data_type) do not match metadata values exactly,\n"
        "3) metadata does not contain the expected files.\n"
        "\nPaste the full output of this script and I will tell you which one it is."
    )


if __name__ == "__main__":
    main()
