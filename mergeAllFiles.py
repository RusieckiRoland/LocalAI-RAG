#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dump files (cs / md / csxaml / py / rag) into a single txt with size, mtime, and SHA256.
'rag' mode concatenates repo files for RAG consumption and injects a per-file commented path header.
"""

import argparse
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

KIND_CHOICES = ("cs", "md", "csxaml", "py", "rag")

# ---------- Hashing ----------

def sha256_of(file_path: Path) -> str:
    """Streamed hash to cope with large files."""
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

# ---------- Mode / prompts ----------

def ask_kind(default="csxaml") -> str:
    """Interactive prompt when --kind is missing."""
    prompt = f"Which file type to dump? ({'/'.join(KIND_CHOICES)}) [{default}] "
    ans = input(prompt).strip().lower()
    if not ans:
        ans = default
    if ans not in KIND_CHOICES:
        print(f"Invalid choice '{ans}'. Use one of: {', '.join(KIND_CHOICES)}.", file=sys.stderr)
        sys.exit(1)
    return ans

# ---------- Discovery helpers ----------

def should_skip_dir(rel_path: Path, excluded: set) -> bool:
    """Skip if any path segment is in excluded list (relative to root)."""
    return any(part in excluded for part in rel_path.parts)

def collect_files(root: Path, kind: str, exclude_folders: set) -> List[Path]:
    """Collect files by kind."""
    if kind == "rag":
        # Comprehensive set for RAG dumps
        patterns = {
            ".cs", ".py", ".md", ".txt",
            ".html", ".htm", ".yml", ".yaml",
            ".json", ".env.example"
        }
    else:
        patterns = {
            "md": {".md"},
            "cs": {".cs"},
            "py": {".py"},
            "csxaml": {".cs", ".xaml"}
        }[kind]

    results: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath_p = Path(dirpath)
        if should_skip_dir(dirpath_p.relative_to(root), exclude_folders):
            dirnames[:] = []  # prune recursion
            continue

        for name in filenames:
            p = dirpath_p / name
            suffix = p.suffix.lower()

            # explicit case for .env.example
            if kind == "rag" and name.lower() == ".env.example":
                results.append(p)
                continue

            if suffix in patterns:
                results.append(p)

    # Deduplicate and sort deterministically
    results = sorted({str(p.resolve()): p for p in results}.values(), key=lambda p: str(p).lower())
    return results

def filter_designer(files: List[Path]) -> List[Path]:
    """Exclude designer/auto-generated C# files."""
    filtered = []
    for p in files:
        if p.suffix.lower() != ".cs":
            filtered.append(p)
            continue
        n = p.name.lower()
        if (
            n.endswith(".designer.cs")
            or n.endswith(".g.cs")
            or n.endswith(".g.i.cs")
            or n == "assemblyinfo.cs"
        ):
            continue
        filtered.append(p)
    return filtered

def filter_dump_artifacts(files: List[Path], out_file: Path, kind: str) -> List[Path]:
    """
    Remove dump artifacts from the input set:
    - the current output file itself
    - any '*_dump_*.txt' (previous py/rag dumps)
    """
    if kind != "rag":
        # For safety we only touch RAG mode here.
        return files

    cleaned: List[Path] = []
    out_file_resolved = out_file.resolve()
    for f in files:
        if f.resolve() == out_file_resolved:
            # Do not read our own output file as input.
            continue
        name = f.name.lower()
        if name.endswith(".txt") and "_dump_" in name:
            # Previous dump artifacts are not useful as RAG input.
            continue
        cleaned.append(f)
    return cleaned

# ---------- Comment style per file kind ----------

def comment_tokens_for(path: Path) -> Tuple[str, Optional[str]]:
    """
    Return (prefix, suffix) tokens to wrap a single-line comment carrying the file path.
    Suffix None means single-line comment; otherwise wrap with prefix+text+suffix.
    """
    ext = path.suffix.lower()
    if path.name.lower() == ".env.example":
        return "# ", None
    if ext in {".csproj", ".xml"}:
        return "<!-- ", " -->"
    if ext in {".html", ".htm", ".md"}:
        return "<!-- ", " -->"
    if ext in {".yml", ".yaml"}:
        return "# ", None
    if ext in {".cs", ".cpp", ".c", ".js", ".ts"}:
        return "// ", None
    if ext in {".py", ".txt"}:
        return "# ", None
    if ext == ".json":
        return "// ", None
    return "# ", None

def write_file_separator(w, title: str) -> None:
    """Write a strong visual separator between files."""
    bar = "═" * 100
    w.write(f"{bar}\n<<< {title} >>>\n{bar}\n\n")

# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="Dump source files into a single text file.")
    parser.add_argument("--root", help="Root folder; defaults to current dir")
    parser.add_argument("--outfile", help="Output file path; auto-generated if omitted")
    parser.add_argument("--kind", choices=KIND_CHOICES, help=f"File kind: {', '.join(KIND_CHOICES)}")
    parser.add_argument("--include-designer", action="store_true",
                        help="Include designer/auto-generated .cs files (applies to cs/csxaml/rag)")
    parser.add_argument("--extra-exclude-folder", nargs="*", default=[],
                        help="Extra folder names to exclude (space-separated)")
    args = parser.parse_args()

    # Resolve root
    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    if not root.exists():
        print(f"Root does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    kind = args.kind or ask_kind(default="csxaml")

    # Output file
    if args.outfile:
        out_file = Path(args.outfile).resolve()
    else:
        leaf = root.name or "root"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = Path(f"{kind}_dump_{leaf}_{stamp}.txt").resolve()

    # Default excluded folders + new ones
    default_exclude = {
        "bin", "obj", ".git", ".vs", "packages", "node_modules", "__pycache__",
        "models", "branches",  # existing exclusions
        ".pytest_cache", ".vscode",  # new exclusions
    }
    exclude_folders = set(x.strip() for x in args.extra_exclude_folder) | default_exclude

    # Header
    header_lines = [
        f"# {kind.upper()} DUMP",
        f"# Root: {root}",
        "# Excluded folders: " + ", ".join(sorted(exclude_folders)),
    ]
    if kind == "rag":
        header_lines.extend([
            "# NOTE: Combined repository artifact for RAG.",
            "# Includes: *.py, *.cs, *.md, *.txt, *.html, .env.example, *.yml, *.yaml, *.json."
        ])
    header_lines.append("")
    out_file.write_text("\n".join(header_lines), encoding="utf-8")

    # Collect files
    files = collect_files(root, kind, exclude_folders)
    if (kind in ("cs", "csxaml", "rag")) and not args.include_designer:
        files = filter_designer(files)

    # NEW: remove dump artifacts (our own outfile, previous *_dump_*.txt)
    files = filter_dump_artifacts(files, out_file, kind)

    with out_file.open("a", encoding="utf-8", newline="") as w:
        for f in files:
            rel = f.relative_to(root)
            title = str(rel)
            write_file_separator(w, title=title)

            try:
                st = f.stat()
                length = st.st_size
                modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
                h = sha256_of(f)
            except (OSError, PermissionError) as ex:
                w.write(f"# ERROR reading file metadata: {ex}\n\n")
                continue

            w.write(f"# Length: {length} bytes | Modified: {modified} | SHA256: {h}\n")

            prefix, suffix = comment_tokens_for(f)
            path_note = f"RAG PATH: {rel}"
            if suffix is None:
                w.write(f"{prefix}{path_note}\n\n")
            else:
                w.write(f"{prefix}{path_note}{suffix}\n\n")

            try:
                w.write(f.read_text(encoding="utf-8", errors="replace"))
            except Exception as ex:
                w.write(f"\n# WARNING: could not read as UTF-8 ({ex}); dumping bytes as repr().\n")
                w.write(repr(f.read_bytes()))
            w.write("\n\n")

    print("Done. Output:", str(out_file))


if __name__ == "__main__":
    main()
