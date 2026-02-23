#!/usr/bin/env python3
"""
Patch tests/e2e/scenarios/pipeline_scenarios.json so that answer outputs match the new
"### Answer:\n..." contract (instead of "[Answer:] ...").

Run from the repo root:
  python patch_pipeline_scenarios_json.py

It will:
- create a .bak backup next to the JSON file
- rewrite the JSON in-place
"""
from __future__ import annotations

import json
from pathlib import Path

SCENARIOS = Path("tests/e2e/scenarios/pipeline_scenarios.json")

ANSWER_TAG = "[Answer:]"

def _patch_answer_string(s: str) -> str:
    if not isinstance(s, str):
        return s
    t = s.strip()
    if not t.startswith(ANSWER_TAG):
        return s
    rest = t[len(ANSWER_TAG):]
    if rest.startswith(" "):
        rest = rest[1:]
    return "### Answer:\n" + rest

def main() -> None:
    if not SCENARIOS.exists():
        raise SystemExit(f"File not found: {SCENARIOS.resolve()}")

    raw = json.loads(SCENARIOS.read_text(encoding="utf-8"))

    changed = 0
    for sc in raw.get("scenarios", []):
        mo = sc.get("model_outputs") or {}
        if not isinstance(mo, dict):
            continue
        for k, arr in list(mo.items()):
            if not isinstance(arr, list):
                continue
            new_arr = []
            for item in arr:
                new_item = _patch_answer_string(item)
                if new_item != item:
                    changed += 1
                new_arr.append(new_item)
            mo[k] = new_arr

    backup = SCENARIOS.with_suffix(SCENARIOS.suffix + ".bak")
    backup.write_text(SCENARIOS.read_text(encoding="utf-8"), encoding="utf-8")

    SCENARIOS.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Patched answer strings: {changed}")
    print(f"Backup saved: {backup}")

if __name__ == "__main__":
    main()
