"""
===========================================
🔹 Vector Index Builder (Main Entry Point)
===========================================

🎯 Purpose:
Builds FAISS vector indexes from repository data (C# code and SQL).

Flow:
1) Lists ZIPs in branches/.
2) User selects a branch (Enter = first).
3) User selects what to build (Enter = BOTH).
4) ZIP is extracted once → branch_root passed to:
   - build_cs_index(branch_root=...)
   - build_sql_index(branch_root=...)

Logs:
- vector_build.log (C#)
- vector_build_sql.log (SQL)

Outputs (next to sources):
- code_index.faiss / metadata.json
- sql_index.faiss  / sql_metadata.json
"""

import sys
import os
import json
import time
import zipfile
import shutil

from vector_db.build_cs_index import build_cs_index
from vector_db.build_sql_index import build_sql_index

# ---------- console utils ----------
def clear_console() -> None:
    """Clear console in a cross-platform way (works in VS Code Terminal/WSL)."""
    if os.getenv("SKIP_CLEAR") == "1":
        return
    try:
        if os.name == "nt":
            os.system("cls")
        else:
            # ANSI: clear screen + move cursor to home
            print("\033[2J\033[H", end="", flush=True)
    except Exception:
        print("\n" * 50)

def human_size(path: str) -> str:
    try:
        b = os.path.getsize(path)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024:
                return f"{b:.0f}{unit}"
            b /= 1024.0
        return f"{b:.0f}PB"
    except Exception:
        return "?"

def choose_branch(zip_files_abs: list[str]) -> str:
    clear_console()
    print("\n📦 Available branch archives in 'branches':")
    for i, zabs in enumerate(zip_files_abs, 1):
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(zabs)))
        print(f"  [{i}]{' *' if i == 1 else ''} {os.path.basename(zabs)}  ({human_size(zabs)}, {mtime})")
    sel = input("Select branch number (Enter = 1): ").strip()
    sel_idx = 1 if not sel else int(sel)
    if sel_idx < 1 or sel_idx > len(zip_files_abs):
        print("❌ Invalid selection.")
        sys.exit(1)
    return zip_files_abs[sel_idx - 1]

def choose_mode() -> str:
    clear_console()
    print("\n🔹 What do you want to build?")
    print("  [1] C# only")
    print("  [2] SQL only")
    print("  [3] Both (C# + SQL) [default]")
    sel = input("Select option (Enter = 3): ").strip()
    if not sel:
        return "both"
    if sel == "1":
        return "cs"
    if sel == "2":
        return "sql"
    return "both"

def load_config(script_dir: str) -> tuple[dict, str]:
    candidates = [
        os.path.join(script_dir, "config.json"),
        os.path.join(script_dir, "..", "config.json"),
    ]
    for c in candidates:
        c_abs = os.path.normpath(c)
        if os.path.isfile(c_abs):
            with open(c_abs, "r", encoding="utf-8") as f:
                return json.load(f), os.path.dirname(c_abs)
    print(
        f"❌ config.json not found. Tried:\n - {os.path.normpath(candidates[0])}\n - {os.path.normpath(candidates[1])}"
    )
    sys.exit(1)

def resolve_path(p: str, base_dir: str) -> str:
    if not p:
        return base_dir
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))

# ---------- extraction helper ----------
def extract_to_named_root(zip_path: str, branches_dir: str) -> str:
    """Extract `zip_path` into a temporary sandbox, then ensure final root is
    `branches/<zipname>` regardless of archive structure.

    - Single top-level folder in archive → move its content under branches/<zipname>.
    - Flat or multi-root archive → move files/folders under branches/<zipname>.

    Returns absolute path to branches/<zipname>.
    """
    zip_base = os.path.splitext(os.path.basename(zip_path))[0]
    expected_root = os.path.join(branches_dir, zip_base)

    tmp_dir = os.path.join(branches_dir, f".extract_{zip_base}_{int(time.time())}")
    os.makedirs(tmp_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(tmp_dir)
        names = [n for n in z.namelist() if not n.endswith("/")]
        roots = {n.split("/", 1)[0] for n in names if "/" in n}
        if names and len(roots) == 1 and all(
            n.startswith(next(iter(roots)) + "/") or n.endswith("/") for n in z.namelist()
        ):
            src_root = os.path.join(tmp_dir, next(iter(roots)))
        else:
            src_root = tmp_dir

    os.makedirs(expected_root, exist_ok=True)

    for entry in os.listdir(src_root):
        src = os.path.join(src_root, entry)
        dst = os.path.join(expected_root, entry)
        if os.path.isdir(src):
            if os.path.exists(dst):
                for root, dirs, files in os.walk(src):
                    rel = os.path.relpath(root, src)
                    target = os.path.join(dst, rel)
                    os.makedirs(target, exist_ok=True)
                    for d in dirs:
                        os.makedirs(os.path.join(target, d), exist_ok=True)
                    for f in files:
                        shutil.move(os.path.join(root, f), os.path.join(target, f))
            else:
                shutil.move(src, dst)
        else:
            if os.path.exists(dst):
                os.remove(dst)
            shutil.move(src, dst)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return expected_root

# ---------- main ----------
def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config, config_dir = load_config(script_dir)

    branches_dir = resolve_path(config.get("branches_dir", "branches"), config_dir)
    os.makedirs(branches_dir, exist_ok=True)

    zip_files_abs = [
        os.path.join(branches_dir, f)
        for f in os.listdir(branches_dir)
        if f.lower().endswith(".zip") and os.path.isfile(os.path.join(branches_dir, f))
    ]
    zip_files_abs.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    if not zip_files_abs:
        print("❌ No ZIP archives found in 'branches/'. Please add one first.")
        sys.exit(1)

    # ----- minimal CI/CD toggle via env vars -----
    chosen_zip_abs = os.getenv("ZIP_PATH") or None  # path or file name under branches/
    mode = os.getenv("MODE") or None               # expected: cs | sql | both

    if chosen_zip_abs:
        # allow file name relative to branches_dir
        if not os.path.isabs(chosen_zip_abs):
            candidate = os.path.join(branches_dir, chosen_zip_abs)
            if os.path.isfile(candidate):
                chosen_zip_abs = candidate
        if not os.path.isfile(chosen_zip_abs):
            print(f"❌ ZIP_PATH not found: {chosen_zip_abs}")
            sys.exit(1)
    else:
        chosen_zip_abs = choose_branch(zip_files_abs)

    if mode:
        mode = mode.strip().lower()
        if mode not in ("cs", "sql", "both"):
            print(f"❌ Invalid MODE='{mode}'. Use one of: cs | sql | both.")
            sys.exit(1)
    else:
        mode = choose_mode()
    # ---------------------------------------------

    print(f"🧩 Extracting {os.path.basename(chosen_zip_abs)} → {branches_dir}")
    branch_root = extract_to_named_root(chosen_zip_abs, branches_dir)
    print(f"✅ Prepared branch root: {branch_root}")

    print(f"\n📁 Selected branch: {os.path.basename(chosen_zip_abs)}")
    print(f"📦 Build mode: {mode.upper()}")

    if mode in ("cs", "both"):
        print("\n🚀 Building C# vector index…")
        build_cs_index(branch_root=branch_root)
    if mode in ("sql", "both"):
        print("\n🚀 Building SQL vector index…")
        build_sql_index(branch_root=branch_root)

    print("\n✅ Done — selected FAISS indexes have been built successfully.")

if __name__ == "__main__":
    main()
