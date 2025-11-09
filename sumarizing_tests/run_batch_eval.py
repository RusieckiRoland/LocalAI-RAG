#!/usr/bin/env python3
# Batch: sortuje pliki SQL wg wielkości (DESC), wysyła każdy do sumarize_tester,
# zbiera wyniki (JSONL + CSV) i raport zbiorczy do łatwego przeglądu.

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))

RUN_SINGLE = os.path.join(HERE, "run_summary_test.py")

DEF_SAVE_ROOT = os.path.join(HERE, "batches")
DEF_ENDPOINT = os.environ.get("CODELLAMA_ENDPOINT", "http://127.0.0.1:5000/search")
DEF_CONSULTANT = os.environ.get("CODELLAMA_CONSULTANT", "sumarize_tester")
DEF_BRANCH = os.environ.get("CODELLAMA_BRANCH", "stable")

def find_sql_files(root: str, recursive: bool, pattern_ext: str = ".sql") -> List[str]:
    files = []
    root = os.path.abspath(root)
    if recursive:
        for d, _, fns in os.walk(root):
            for fn in fns:
                if fn.lower().endswith(pattern_ext):
                    files.append(os.path.join(d, fn))
    else:
        for fn in os.listdir(root):
            p = os.path.join(root, fn)
            if os.path.isfile(p) and fn.lower().endswith(pattern_ext):
                files.append(p)
    return files

def sort_by_size_desc(paths: List[str]) -> List[str]:
    return sorted(paths, key=lambda p: os.path.getsize(p), reverse=True)

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def call_single(sql_path: str,
                emit: str,
                endpoint: str,
                consultant: str,
                branch: str,
                gate_min_score: Optional[int],
                gate_no_problems: bool,
                gate_fail_cats: Optional[str],
                save_dir: str) -> Dict[str, Any]:
    """Wywołuje run_summary_test.py i zwraca zparsowany stdout (dict)."""
    cmd = [
        sys.executable, RUN_SINGLE,
        "--sql-path", sql_path,
        "--emit", emit,
        "--endpoint", endpoint,
        "--consultant", consultant,
        "--branch", branch,
        "--with-summary",
        "--report-jsonl", os.path.join(save_dir, "results.jsonl"),
        "--save-dir", os.path.join(save_dir, "runs"),
    ]
    if gate_min_score is not None:
        cmd += ["--gate-min-score", str(gate_min_score)]
    if gate_no_problems:
        cmd += ["--gate-no-problems"]
    if gate_fail_cats:
        cmd += ["--gate-fail-cats", gate_fail_cats]

    try:
        res = subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=REPO_ROOT)
    except Exception as ex:
        return {
            "meta": {"sql_path": sql_path},
            "error": f"subprocess error: {ex}",
            "exit_code": -1,
        }

    stdout = (res.stdout or "").strip()
    stderr = (res.stderr or "").strip()

    try:
        obj = json.loads(stdout)
    except json.JSONDecodeError:
        obj = {"raw_stdout": stdout}

    obj.setdefault("meta", {})
    obj["meta"].setdefault("sql_path", sql_path)
    obj["exit_code"] = res.returncode
    if stderr:
        obj["stderr"] = stderr
    return obj

def write_csv_index(path: str, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(os.path.dirname(path))
    fieldnames = [
        "sql_path", "size_bytes",
        "score", "verdict", "problems_count",
        "problem_categories",
        "gate_passed", "gate_reasons",
        "phantom_rsets"
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_cat: Dict[str, int] = {}
    verdicts: Dict[str, int] = {}
    scores: List[float] = []
    worst = []

    for r in rows:
        sc = r.get("score")
        if isinstance(sc, (int, float)):
            scores.append(float(sc))
        v = r.get("verdict") or ""
        verdicts[v] = verdicts.get(v, 0) + 1
        for c in r.get("problem_categories", []):
            by_cat[c] = by_cat.get(c, 0) + 1

    rows_sorted = sorted(rows, key=lambda x: (x.get("score", 9999), -x.get("size_bytes", 0)))
    worst = rows_sorted[:50]  # top 50 najgorszych

    return {
        "count": len(rows),
        "avg_score": (sum(scores) / len(scores)) if scores else None,
        "verdicts": verdicts,
        "problem_categories": sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True),
        "worst_top50": [
            {
                "sql_path": r["sql_path"],
                "score": r.get("score"),
                "problems_count": r.get("problems_count"),
                "phantom_rsets": r.get("phantom_rsets"),
                "size_bytes": r.get("size_bytes"),
            }
            for r in worst
        ],
    }

def main():
    ap = argparse.ArgumentParser(description="Batch evaluator for SQL summaries (sort by size desc).")
    ap.add_argument("--sql-dir", required=True, help="Katalog z plikami .sql (np. branches/.../sql_bundle/docs/bodies)")
    ap.add_argument("--recursive", action="store_true", help="Skanuj rekurencyjnie (domyślnie: FALSE)")
    ap.add_argument("--limit", type=int, help="Opcjonalny limit liczby plików")
    ap.add_argument("--emit", default="min", choices=["min", "std", "full"])

    # LLM/backend
    ap.add_argument("--endpoint", default=DEF_ENDPOINT)
    ap.add_argument("--consultant", default=DEF_CONSULTANT)
    ap.add_argument("--branch", default=DEF_BRANCH)

    # Gates
    ap.add_argument("--gate-min-score", type=int, default=9)
    ap.add_argument("--gate-no-problems", action="store_true")
    ap.add_argument("--gate-fail-cats", default="result_sets,parameters")

    # Output
    ap.add_argument("--save-root", default=DEF_SAVE_ROOT, help="Gdzie tworzyć paczkę wyników")
    args = ap.parse_args()

    # Zbierz i posortuj pliki
    files = find_sql_files(args.sql_dir, recursive=args.recursive)
    if not files:
        print(json.dumps({"error": "no_sql_files_found", "sql_dir": args.sql_dir}))
        sys.exit(1)
    files_sorted = sort_by_size_desc(files)
    if args.limit:
        files_sorted = files_sorted[:args.limit]

    # Katalog wsadowy
    batch_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = os.path.join(args.save_root, f"batch_{batch_stamp}")
    runs_dir = os.path.join(batch_dir, "runs")
    ensure_dir(runs_dir)

    results: List[Dict[str, Any]] = []
    for i, p in enumerate(files_sorted, 1):
        sz = os.path.getsize(p)
        print(f"[{i}/{len(files_sorted)}] {p}  ({sz} bytes)")
        res = call_single(
            sql_path=p,
            emit=args.emit,
            endpoint=args.endpoint,
            consultant=args.consultant,
            branch=args.branch,
            gate_min_score=args.gate_min_score,
            gate_no_problems=args.gate_no_problems,
            gate_fail_cats=args.gate_fail_cats,
            save_dir=batch_dir,
        )

        # wyciągnij pola do indeksu
        score = None
        verdict = ""
        probs = 0
        cats = []
        phantom = None
        gate_passed = None
        gate_reasons = []

        ev = res.get("evaluation") or res  # fallback
        if isinstance(ev, dict):
            score = ev.get("score")
            verdict = ev.get("verdict", "")
            pr = ev.get("problems") or []
            probs = len(pr)
            for pr_item in pr:
                if isinstance(pr_item, dict) and "category" in pr_item:
                    cats.append(pr_item["category"])

        det = res.get("deterministic") or {}
        if isinstance(det, dict):
            phantom = det.get("phantom_rsets")

        gates = res.get("gates") or {}
        if isinstance(gates, dict):
            gate_passed = gates.get("passed")
            gate_reasons = gates.get("reasons") or gates.get("result", {}).get("reasons") or []

        row = {
            "sql_path": p,
            "size_bytes": sz,
            "score": score,
            "verdict": verdict,
            "problems_count": probs,
            "problem_categories": list(sorted(set(cats))),
            "gate_passed": gate_passed,
            "gate_reasons": "; ".join(gate_reasons) if gate_reasons else "",
            "phantom_rsets": phantom,
        }
        results.append(row)

    # zapis CSV + summary JSON
    index_csv = os.path.join(batch_dir, "index.csv")
    write_csv_index(index_csv, results)

    summary_json = summarize(results)
    with open(os.path.join(batch_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary_json, f, ensure_ascii=False, indent=2)

    # Wynik końcowy na stdout (krótki pointer)
    out = {
        "batch_dir": batch_dir,
        "files": len(results),
        "index_csv": index_csv,
        "results_jsonl": os.path.join(batch_dir, "results.jsonl"),
        "summary_json": os.path.join(batch_dir, "summary.json"),
        "hint": "Otwórz index.csv i posortuj po kolumnie 'score' rosnąco, żeby zacząć od najgorszych."
    }
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
