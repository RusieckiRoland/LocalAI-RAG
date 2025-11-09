#!/usr/bin/env python3
# File: summarizing_tests/run_summary_test.py
# WSL/Ubuntu helper: sends SQL + summary to CodeLlama (consultant: sumarize_tester),
# prints JSON result, applies quality gates, and performs a deterministic "phantom_rsets" check.
# Additionally saves score-prefixed duplicates under by_score/ with sNN_ prefix for easy sorting.

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
import pathlib
import requests
from typing import Optional, List, Dict, Any
import re
import shutil

# ------------------------- defaults / env -------------------------

DEFAULT_ENDPOINT = os.environ.get("CODELLAMA_ENDPOINT", "http://127.0.0.1:5000/search")
DEFAULT_CONSULTANT = os.environ.get("CODELLAMA_CONSULTANT", "sumarize_tester")
DEFAULT_BRANCH = os.environ.get("CODELLAMA_BRANCH", "stable")
DEFAULT_TIMEOUT = int(os.environ.get("CODELLAMA_TIMEOUT", "180"))

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]  # .../Repo/RAG
DEFAULT_REPORT = "summarizing_tests/eval_report.jsonl"

# ------------------------- utils -------------------------

def normalize_path(p: Optional[str]) -> Optional[str]:
    """Resolve a path to an absolute file path if possible (tries repo-relative as well)."""
    if not p:
        return None
    p = os.path.expanduser(p)
    if os.path.isabs(p):
        return p
    cand1 = os.path.abspath(p)
    if os.path.isfile(cand1):
        return cand1
    cand2 = os.path.join(str(REPO_ROOT), p)
    if os.path.isfile(cand2):
        return cand2
    return cand1

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def write_jsonl(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def safe_name(s: str) -> str:
    """Make a filesystem-friendly name (limited length; non-alnum replaced by underscores)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:180]

# ------------------------- SQL helpers (deterministic checks) -------------------------

def strip_sql_comments(sql: str) -> str:
    """Remove /* ... */ and -- comments from SQL text."""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    sql = re.sub(r"(?m)--.*?$", "", sql)
    return sql

def _is_select_var_assignment(line_lc: str) -> bool:
    # 'select @x = ...' or 'select top 1 @x = ...'
    return bool(re.match(r"^\s*select\s+(top\s+\d+\s+)?@", line_lc))

def _is_select_part_of_insert(prev_nonempty_lc: str) -> bool:
    # SELECT as part of 'INSERT INTO ... SELECT ...'
    return "insert into" in (prev_nonempty_lc or "")

def has_top_level_select(sql: str) -> bool:
    """
    Detects a top-level SELECT that returns rows:
      - line starts with 'select'
      - must NOT contain ' into '
      - must NOT assign to variables (@...)
      - must NOT be part of 'INSERT INTO ... SELECT ...'
    """
    s = strip_sql_comments(sql)
    prev_nonempty = ""
    for raw in s.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        lc = line.lstrip().lower()
        if lc.startswith("select "):
            if " into " in lc:
                prev_nonempty = lc; continue
            if _is_select_var_assignment(lc):
                prev_nonempty = lc; continue
            if _is_select_part_of_insert(prev_nonempty):
                prev_nonempty = lc; continue
            return True
        prev_nonempty = lc
    return False

def det_check_phantom_rsets(sql_text: str, summary_obj: Dict[str, Any]) -> bool:
    """
    Deterministic check:
    - If the summary reports result sets (out.rsets not empty)
    - but the SQL has NO top-level SELECT returning rows,
    then flag 'phantom_rsets' as True.
    """
    out = (summary_obj or {}).get("out") or {}
    rsets = out.get("rsets") or []
    return bool(rsets and not has_top_level_select(sql_text or ""))

# ------------------------- summarizer -------------------------

def run_tsql_summarizer(sql_path_abs: str, emit: str = "min") -> str:
    """
    Run tsql_summarizer module and return its JSON output as a string.
    Exits with diagnostics if the process fails or returns invalid JSON.
    """
    cmd = [sys.executable, "-m", "tsql_summarizer", sql_path_abs, "--emit", emit]
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=str(REPO_ROOT))
        out = res.stdout.strip()
        i = out.find("{")
        if i > 0:
            out = out[i:]
        json.loads(out)  # validate JSON early
        return out
    except subprocess.CalledProcessError as e:
        sys.stderr.write("ERROR: tsql_summarizer failed.\n")
        if e.stdout:
            sys.stderr.write("--- STDOUT ---\n" + e.stdout + "\n")
        if e.stderr:
            sys.stderr.write("--- STDERR ---\n" + e.stderr + "\n")
        sys.exit(2)
    except json.JSONDecodeError:
        sys.stderr.write("ERROR: summarizer output is not valid JSON.\n")
        sys.stderr.write(out + "\n")
        sys.exit(3)

# ------------------------- payload -------------------------

def build_query(sql_text: str, summary_json: str) -> str:
    """Build the prompt payload passed to the backend (SQL + SUMMARY blocks)."""
    return (
        "ORIGINAL:\n\n"
        "```sql\n" + sql_text + "\n```\n\n"
        "SUMMARY:\n\n"
        "```json\n" + summary_json + "\n```"
    )

def post_search(endpoint: str, query_text: str, consultant: str, branch: str,
                session_id: Optional[str], timeout: int):
    """POST a search request to the backend."""
    headers = {"X-Session-ID": session_id or str(uuid.uuid4())}
    payload = {"query": query_text, "consultant": consultant, "branch": branch, "translateChat": False}
    r = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def extract_json(results_field) -> dict:
    """
    Extract a JSON object from either:
    - a dict (returned as-is), or
    - a string containing JSON (first '{' onwards).
    """
    if isinstance(results_field, dict):
        return results_field
    if not isinstance(results_field, str):
        raise ValueError("Unexpected results type (not str/dict)")
    s = results_field.strip()
    i = s.find("{")
    if i == -1:
        raise ValueError("No JSON object found in results")
    return json.loads(s[i:])

# ------------------------- gates -------------------------

def parse_fail_cats(s: Optional[str]) -> List[str]:
    """Parse a comma-separated category list into a list of strings."""
    if not s:
        return []
    return [c.strip() for c in s.split(",") if c.strip()]

def eval_gates(evaluation: Dict[str, Any],
               gate_min_score: Optional[int],
               gate_no_problems: bool,
               gate_fail_cats: List[str]) -> Dict[str, Any]:
    """
    Evaluate quality gates:
    - score threshold
    - no problems present
    - forbidden categories not present
    """
    score = evaluation.get("score")
    problems = evaluation.get("problems") or []
    cats = {p.get("category") for p in problems if isinstance(p, dict)}
    reasons = []

    if gate_min_score is not None and isinstance(score, (int, float)):
        if score < gate_min_score:
            reasons.append(f"score {score} < gate_min_score {gate_min_score}")
    elif gate_min_score is not None:
        reasons.append("score is missing or not numeric")

    if gate_no_problems and len(problems) > 0:
        reasons.append(f"{len(problems)} problems present but gate_no_problems is set")

    if gate_fail_cats:
        hit = cats.intersection(set(gate_fail_cats))
        if hit:
            reasons.append(f"forbidden categories present: {sorted(hit)}")

    passed = len(reasons) == 0
    return {"passed": passed, "reasons": reasons}

# ------------------------- main -------------------------

def main():
    ap = argparse.ArgumentParser(
        description=(
            "SQL -> tsql_summarizer -> sumarize_tester (JSON only) + gates/report "
            "+ deterministic checks + score-prefixed files."
        )
    )
    ap.add_argument("--sql-path", help="Path to the .sql file (Linux).")
    ap.add_argument("--summary-path", help="Optional: use a ready summary.json instead of running tsql_summarizer.")
    ap.add_argument("--emit", default="min", choices=["min", "std", "full"], help="Emission level for tsql_summarizer.")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Backend /search URL.")
    ap.add_argument("--consultant", default=DEFAULT_CONSULTANT, help="Consultant identifier to use.")
    ap.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch identifier to use.")
    ap.add_argument("--session-id", help="Optional X-Session-ID to send to the backend.")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds.")
    ap.add_argument("--save-dir", default="summarizing_tests/output", help="Directory to store run artifacts.")
    ap.add_argument("--with-summary", action="store_true", help="Print summary and meta to stdout alongside evaluation.")
    # Gates
    ap.add_argument("--gate-min-score", type=int, help="Minimum score required for PASS (optional).")
    ap.add_argument("--gate-no-problems", action="store_true", help="Require problems[] to be empty.")
    ap.add_argument("--gate-fail-cats", help="Comma-separated list of categories that cause FAIL, e.g. 'result_sets,parameters'.")
    ap.add_argument("--report-jsonl", default=DEFAULT_REPORT, help="Path to the aggregate JSONL report.")
    args = ap.parse_args()

    if not args.summary_path and not args.sql_path:
        ap.error("Required: --sql-path OR --summary-path")

    ensure_dir(args.save_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(args.save_dir, f"run_{stamp}")

    # 1) SQL (optional)
    sql_text = ""
    sql_path_abs = None
    if args.sql_path:
        sql_path_abs = normalize_path(args.sql_path)
        if not os.path.isfile(sql_path_abs):
            sys.stderr.write(f"ERROR: SQL file not found: {args.sql_path}\n")
            sys.exit(1)
        sql_text = read_text(sql_path_abs)
        with open(base + "_original.sql", "w", encoding="utf-8") as f:
            f.write(sql_text)

    # 2) SUMMARY (from file or generated)
    if args.summary_path:
        summary_path_abs = normalize_path(args.summary_path)
        if not os.path.isfile(summary_path_abs):
            sys.stderr.write(f"ERROR: summary file not found: {args.summary_path}\n")
            sys.exit(1)
        summary_json_str = read_text(summary_path_abs)
    else:
        if not sql_path_abs:
            sys.stderr.write("ERROR: Missing --sql-path (required when --summary-path is not provided).\n")
            sys.exit(1)
        summary_json_str = run_tsql_summarizer(sql_path_abs, args.emit)

    # validate summary JSON
    try:
        summary_obj = json.loads(summary_json_str)
    except json.JSONDecodeError as ex:
        sys.stderr.write(f"ERROR: summary is not valid JSON: {ex}\n")
        sys.exit(3)

    with open(base + "_summary.json", "w", encoding="utf-8") as f:
        f.write(summary_json_str)

    # 3) Query -> backend
    query_text = build_query(sql_text, summary_json_str)
    try:
        resp = post_search(args.endpoint, query_text, args.consultant, args.branch, args.session_id, args.timeout)
    except requests.RequestException as ex:
        sys.stderr.write(f"ERROR: backend request failed: {ex}\n")
        sys.exit(4)

    with open(base + "_response_full.json", "w", encoding="utf-8") as f:
        json.dump(resp, f, ensure_ascii=False, indent=2)

    # 4) Evaluation JSON
    try:
        evaluation = extract_json(resp.get("results"))
    except Exception as ex:
        sys.stderr.write(f"ERROR: could not extract JSON from results: {ex}\n")
        with open(base + "_results_raw.txt", "w", encoding="utf-8") as f:
            f.write(str(resp.get("results")))
        sys.exit(5)

    with open(base + "_evaluation.json", "w", encoding="utf-8") as f:
        json.dump(evaluation, f, ensure_ascii=False, indent=2)

    # 5) Gates (LLM-based)
    fail_cats = parse_fail_cats(args.gate_fail_cats)
    gate_result = eval_gates(
        evaluation=evaluation,
        gate_min_score=args.gate_min_score,
        gate_no_problems=args.gate_no_problems,
        gate_fail_cats=fail_cats
    )

    # 6) Deterministic check: phantom_rsets
    phantom = det_check_phantom_rsets(sql_text, summary_obj)
    det = {"phantom_rsets": phantom}
    if phantom:
        gate_result["passed"] = False
        gate_result.setdefault("reasons", []).append("phantom_rsets")

    # 7) Report line (append to JSONL)
    report_line = {
        "ts": stamp,
        "sql_path": sql_path_abs or "",
        "consultant": args.consultant,
        "branch": args.branch,
        "evaluation": evaluation,
        "summary": summary_obj if args.with_summary else None,
        "gates": {
            "min_score": args.gate_min_score,
            "no_problems": args.gate_no_problems,
            "fail_cats": fail_cats,
            "result": gate_result,
            "deterministic": det
        }
    }
    try:
        write_jsonl(args.report_jsonl, report_line)
    except Exception as ex:
        sys.stderr.write(f"WARN: could not write JSONL report: {ex}\n")

    # 8) Duplicates in by_score/ with sNN_ prefix
    try:
        score = evaluation.get("score")
        try:
            score_int = int(score)
        except Exception:
            score_int = 0
        score_int = max(0, min(10, score_int))
        status = "PASS" if gate_result.get("passed") else "FAIL"
        verdict = safe_name(str(evaluation.get("verdict") or ""))
        sql_base = safe_name(os.path.basename(sql_path_abs or "no_sql.sql"))
        prefix_dir = os.path.join(args.save_dir, "by_score")
        ensure_dir(prefix_dir)
        pref = f"s{score_int:02d}_{status}_{verdict}__{sql_base}__{stamp}"

        # Save copies with the prefix (easy sorting in file explorers)
        shutil.copyfile(base + "_evaluation.json", os.path.join(prefix_dir, pref + "_evaluation.json"))
        shutil.copyfile(base + "_summary.json",    os.path.join(prefix_dir, pref + "_summary.json"))
        if os.path.exists(base + "_original.sql"):
            shutil.copyfile(base + "_original.sql", os.path.join(prefix_dir, pref + "_original.sql"))
    except Exception as ex:
        sys.stderr.write(f"WARN: could not create prefixed copies: {ex}\n")

    # 9) Stdout payload
    if args.with_summary:
        out = {
            "evaluation": evaluation,
            "summary": summary_obj,
            "meta": {
                "sql_path": sql_path_abs or "",
                "consultant": args.consultant,
                "branch": args.branch
            },
            "gates": gate_result,
            "deterministic": det
        }
    else:
        out = evaluation

    print(json.dumps(out, ensure_ascii=False))

    # 10) Exit code by gates + deterministic checks
    sys.exit(0 if gate_result["passed"] else 1)

if __name__ == "__main__":
    main()
