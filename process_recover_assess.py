# File: process_analyze_compare.py

import os
import re
import sys
import json
import glob
import argparse
import requests
from typing import Optional

# --- Config ---
DEFAULT_API_URL = os.getenv("SEARCH_API_URL", "http://localhost:5000/search")
DEFAULT_BRANCH  = os.getenv("SEARCH_BRANCH", "stable")
DEFAULT_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "180"))  # read-timeout (s)

SECTION_LINE_3 = "---"
SECTION_LINE_4 = "----"
SECTION_LINE_5 = "-----"

# ---------- I/O helpers ----------
def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

# ---------- JSON helpers ----------
def extract_first_json_object(text: str) -> Optional[str]:
    """
    Extract the first well-balanced JSON object (from the first '{' to its matching '}').
    Ignores braces inside strings. Returns the raw JSON substring or None.
    """
    if not text:
        return None
    i = text.find("{")
    if i == -1:
        return None

    in_str = False
    esc = False
    depth = 0
    start = None

    for idx in range(i, len(text)):
        ch = text[idx]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start:idx+1]
    return None

def prettify_if_json(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except Exception:
        return text

def compact_json_if_possible(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return text

# ---------- Summarizer ----------
def make_summary(sql_text: str, mode: str = "min") -> str:
    """
    Return a compact JSON summary of the SQL (for RAG).
    """
    try:
        from tsql_summarizer.api import summarize_tsql, make_compact
    except Exception as e:
        raise RuntimeError("tsql_summarizer package not available in PYTHONPATH") from e
    payload = summarize_tsql(sql_text)
    compact = make_compact(payload, mode=mode)
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

# ---------- HTTP ----------
def post_to_api(query_text: str,
                consultant: str,
                api_url: str,
                branch: str = DEFAULT_BRANCH,
                session_id: Optional[str] = None,
                timeout: int = DEFAULT_TIMEOUT) -> dict | str:
    headers = {}
    if session_id:
        headers["X-Session-ID"] = session_id
    body = {
        "query": query_text,
        "consultant": consultant,
        "branch": branch,
        "translateChat": False
    }
    r = requests.post(api_url, json=body, headers=headers, timeout=(15, timeout))
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return r.text

def extract_text(api_response: dict | str) -> str:
    """
    Extract a textual payload from API response (which may be str/dict/list).

    - If the top-level looks like an ANALYST/COMPARER object already
      (keys like "kind"/"score"/"match"/"columns"/"params"/"reads_from"/"writes_to"),
      return json.dumps(obj).
    - Otherwise try common fields; if none match, return a JSON dump of the object.
    """
    if api_response is None:
        return ""
    if isinstance(api_response, str):
        return api_response
    if isinstance(api_response, dict):
        if any(k in api_response for k in ("kind", "score", "match", "columns", "params", "reads_from", "writes_to")):
            return json.dumps(api_response, ensure_ascii=False)
        res = (
            api_response.get("results")
            or api_response.get("answer")
            or api_response.get("content")
            or api_response.get("message")
            or api_response.get("result")
        )
        if isinstance(res, str):
            return res
        if isinstance(res, dict):
            return json.dumps(res, ensure_ascii=False)
        if isinstance(res, list):
            parts = []
            for x in res:
                if isinstance(x, str):
                    parts.append(x)
                elif isinstance(x, dict):
                    for k in ("text", "content", "answer", "message", "result"):
                        if k in x and isinstance(x[k], str):
                            parts.append(x[k]); break
                    else:
                        parts.append(json.dumps(x, ensure_ascii=False))
            return "\n".join(parts)
        return json.dumps(api_response, ensure_ascii=False)
    return str(api_response)

# ---------- Payload builders ----------
def normalize_analysis_output(raw_text: str) -> str:
    """
    Ensure the analysis block is a CLEAN JSON object string.
    - If the model added chatter, extract the first {...} object.
    - If it is a JSON text already, compact it.
    """
    if not raw_text:
        return "{}"
    try:
        return compact_json_if_possible(raw_text)
    except Exception:
        pass
    obj = extract_first_json_object(raw_text)
    if obj:
        return compact_json_if_possible(obj)
    return raw_text.strip()

def build_comparer_payload(analysis_sql: str, analysis_json: str) -> str:
    """
    COMPARER expects two blocks: FROM_SQL: {...} and FROM_JSON: {...}
    """
    clean_sql   = normalize_analysis_output(analysis_sql)
    clean_short = normalize_analysis_output(analysis_json)
    return (
        "FROM_SQL:\n"  + clean_sql   + "\n\n"
        "FROM_JSON:\n" + clean_short
    )

# ---------- Report ----------
def build_report(score: int,
                 original_sql: str,
                 shortcut: str,
                 analysis_sql: str,
                 analysis_shortcut: str,
                 comparison_text: str) -> str:
    parts = []
    parts.append(f"{score:02d}/10\n")
    parts.append("Original:\n" + SECTION_LINE_3)
    parts.append((original_sql or "").strip() + "\n")
    parts.append("Shortcut\n" + SECTION_LINE_3)
    parts.append(prettify_if_json((shortcut or "").strip()) + "\n")
    parts.append("Assessment (SQL)\n" + SECTION_LINE_4)
    parts.append(prettify_if_json((analysis_sql or "").strip()) + "\n")
    parts.append("Assessment (Shortcut)\n" + SECTION_LINE_4)
    parts.append(prettify_if_json((analysis_shortcut or "").strip()) + "\n")
    parts.append("Comparison\n" + SECTION_LINE_5)
    parts.append(prettify_if_json((comparison_text or "").strip()) + "\n")
    return "\n".join(parts)

def score_to_dir(score: int) -> str:
    """
    Folder by score:
      - 0        -> "0"
      - 1..9     -> "01".."09"
      - 10       -> "10"
    """
    if score <= 0:
        return "0"
    if score >= 10:
        return "10"
    return f"{score:02d}"

def parse_score(comparison_text: str) -> int:
    """
    Prefer: extract the first JSON object and read 'score'.
    Fallback: look for NN/10 pattern.
    """
    if not comparison_text:
        return 0

    def _extract_first_json_object(text: str):
        i = text.find("{")
        if i == -1:
            return None
        in_str = False; esc = False; depth = 0; start = None
        for idx in range(i, len(text)):
            ch = text[idx]
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
            else:
                if ch == '"': in_str = True
                elif ch == "{":
                    if depth == 0: start = idx
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start is not None:
                        return text[start:idx+1]
        return None

    jtxt = _extract_first_json_object(comparison_text)
    if jtxt:
        try:
            obj = json.loads(jtxt)
            val = int(obj.get("score", 0))
            return max(0, min(val, 10))
        except Exception:
            pass

    m = re.search(r"\b(\d{1,2})\s*/\s*10\b", comparison_text)
    return max(0, min(int(m.group(1)), 10)) if m else 0


# ---------- Per-file run ----------
def process_one_file(sql_path: str,
                     api_url: str,
                     branch: str,
                     outdir: str,
                     emit_mode: str,
                     session_id: Optional[str]):
    # 1) Read original SQL
    original_sql = read_text(sql_path)

    # 2) Make JSON shortcut (RAG summary)
    shortcut = make_summary(original_sql, mode=emit_mode)

    # 3) Analysis from full SQL
    analysis_sql_resp = post_to_api(original_sql,
                                    consultant="sql_json_analyst",
                                    api_url=api_url,
                                    branch=branch,
                                    session_id=session_id)
    analysis_sql = extract_text(analysis_sql_resp)

    # 4) Analysis from JSON shortcut
    analysis_shortcut_resp = post_to_api(shortcut,
                                         consultant="sql_json_analyst",
                                         api_url=api_url,
                                         branch=branch,
                                         session_id=session_id)
    analysis_shortcut = extract_text(analysis_shortcut_resp)

    # 5) Comparison by COMPARER
    comparer_payload = build_comparer_payload(analysis_sql, analysis_shortcut)
    comparer_resp = post_to_api(comparer_payload,
                                consultant="comparer",
                                api_url=api_url,
                                branch=branch,
                                session_id=session_id)
    comparison_text = extract_text(comparer_resp)

    # 6) Score & paths
    score = parse_score(comparison_text)
    bucket = score_to_dir(score)

    # 7) Build report text
    report_text = build_report(score,
                               original_sql=original_sql,
                               shortcut=shortcut,
                               analysis_sql=normalize_analysis_output(analysis_sql),
                               analysis_shortcut=normalize_analysis_output(analysis_shortcut),
                               comparison_text=comparison_text)

    # 8) Save
    base = os.path.basename(sql_path).replace("\n", " ").replace("\r", " ")
    out_name = f"{score:02d}__{base}.txt"
    out_path = os.path.join(outdir, bucket, out_name)
    write_text(out_path, report_text)
    return out_path, score

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(
        description="SQL → (ANALYST: SQL & JSON) → COMPARER | save by score into separate folders"
    )
    ap.add_argument("path", help="Path to a .sql file or a directory with .sql files")
    ap.add_argument("--api-url", default=DEFAULT_API_URL, help="URL of the /search endpoint")
    ap.add_argument("--branch",  default=DEFAULT_BRANCH,  help="Consultant branch name (default: stable)")
    ap.add_argument("--session-id", default=None, help="Optional X-Session-ID (to maintain a session)")
    ap.add_argument("--outdir", default="./out_compare", help="Base directory for reports")
    ap.add_argument("--emit", choices=["lite","min","ultra","rag"], default="rag",
                    help="Summarizer compaction mode (default: rag)")
    ap.add_argument("--recursive", action="store_true",
                    help="If the path is a directory, process *.sql recursively")
    args = ap.parse_args()

    path    = args.path
    api_url = args.api_url
    branch  = args.branch
    outdir  = args.outdir
    session = args.session_id
    emit    = args.emit

    # Collect files
    if os.path.isdir(path):
        pattern = "**/*.sql" if args.recursive else "*.sql"
        files = glob.glob(os.path.join(path, pattern), recursive=args.recursive)
        files.sort()
        if not files:
            print("No .sql files found in the given location.", file=sys.stderr)
            sys.exit(2)
    else:
        files = [path]

    # Process
    results = []
    for fp in files:
        try:
            out_path, score = process_one_file(fp, api_url, branch, outdir, emit, session)
            print(f"[OK] {score:02d} -> {out_path}")
            results.append((fp, score, out_path))
        except requests.HTTPError as e:
            print(f"[HTTP {e.response.status_code}] {fp}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] {fp}: {e}", file=sys.stderr)

    print("\n=== Pipeline finished ===")
    print(f"- Files: {len(results)}")
    buckets = {}
    for _, sc, _ in results:
        key = score_to_dir(sc)
        buckets[key] = buckets.get(key, 0) + 1
    if buckets:
        print("- Score distribution:", ", ".join(f"{k}:{v}" for k, v in sorted(buckets.items())))

if __name__ == "__main__":
    main()
