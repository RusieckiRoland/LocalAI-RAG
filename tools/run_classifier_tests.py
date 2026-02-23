#!/usr/bin/env python3
"""
run_classifier_tests.py

Runs a labeled classification test set against a classifier implemented in a Python file (e.g. old.py).

Default expectations:
- Dataset: JSON array of objects: { "id": "...", "kind": "dotnet|sql|dotnet_with_sql|unknown", "text": "..." }
- Classifier module file exposes one of:
    - classify_text(text: str) -> result (preferred)
    - classify_text_compact(text: str) -> (kind: str, confidence: float)
    - classify(text: str) -> ...

The runner is defensive:
- It dynamically imports the classifier module from a path.
- It tries multiple function names.
- It normalizes different return shapes:
    - dataclass/object with .kind and .confidence
    - dict with 'kind'/'confidence'
    - tuple/list (kind, confidence)
    - plain string kind (confidence assumed 0.5)

Exit code:
- 0 on success
- 2 on config/import errors
- 3 if --fail-under is set and accuracy is below threshold
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


ALLOWED_KINDS = {"dotnet", "sql", "dotnet_with_sql", "unknown"}


def _load_module_from_path(module_path: Path) -> Any:
    if not module_path.exists():
        raise FileNotFoundError(f"Classifier module not found: {module_path}")

    spec = importlib.util.spec_from_file_location(module_path.stem, str(module_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create import spec for: {module_path}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _pick_classifier_fn(mod: Any, fn_name: Optional[str]) -> Callable[[str], Any]:
    candidates = []
    if fn_name:
        candidates.append(fn_name)
    candidates += ["classify_text", "classify_text_compact", "classify", "predict"]

    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn

    public_callables = sorted(
        n for n in dir(mod)
        if not n.startswith("_") and callable(getattr(mod, n, None))
    )
    raise AttributeError(
        "No classifier function found. Tried: "
        + ", ".join(candidates)
        + "\nAvailable callables in module: "
        + ", ".join(public_callables[:50])
    )


def _norm_kind(x: Any) -> str:
    if x is None:
        return "unknown"

    # Enum-like
    if hasattr(x, "value"):
        try:
            v = getattr(x, "value")
            if isinstance(v, str):
                x = v
        except Exception:
            pass

    if isinstance(x, str):
        k = x.strip().lower()
        # accept a few aliases
        if k in ("dotnet_with_sql", "dotnet+sql", "dotnet_sql", "csharp_with_sql", "c#_with_sql"):
            return "dotnet_with_sql"
        if k in ("csharp", "c#", "cs", "net", "dotnet"):
            return "dotnet"
        if k in ("tsql", "t-sql", "mssql"):
            return "sql"
        if k in ("unk", "unknown", "mixed"):
            return "unknown"
        return k

    # Fallback
    return str(x).strip().lower()


def _extract_kind_conf(result: Any) -> Tuple[str, float]:
    """
    Normalize different possible result shapes into (kind, confidence).
    """
    # tuple/list (kind, conf)
    if isinstance(result, (tuple, list)) and len(result) >= 2:
        kind = _norm_kind(result[0])
        try:
            conf = float(result[1])
        except Exception:
            conf = 0.5
        return kind, _clamp01(conf)

    # dict
    if isinstance(result, dict):
        kind = _norm_kind(result.get("kind") or result.get("label") or result.get("type"))
        conf_val = result.get("confidence") or result.get("score") or result.get("prob")
        try:
            conf = float(conf_val) if conf_val is not None else 0.5
        except Exception:
            conf = 0.5
        return kind, _clamp01(conf)

    # dataclass or object with attrs
    if is_dataclass(result) or hasattr(result, "__dict__") or hasattr(result, "kind"):
        kind_attr = getattr(result, "kind", None)
        conf_attr = getattr(result, "confidence", None)

        kind = _norm_kind(kind_attr)

        try:
            conf = float(conf_attr) if conf_attr is not None else 0.5
        except Exception:
            conf = 0.5

        return kind, _clamp01(conf)

    # plain string
    if isinstance(result, str):
        return _norm_kind(result), 0.5

    return "unknown", 0.5


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _load_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Dataset must be a JSON array.")

    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"Dataset row #{idx} is not an object.")
        if "text" not in row or "kind" not in row:
            raise ValueError(f"Dataset row #{idx} missing required keys: 'text' and/or 'kind'.")
        out.append(row)
    return out


def _confusion_matrix(rows: Iterable[Tuple[str, str]]) -> Dict[str, Counter]:
    m: Dict[str, Counter] = defaultdict(Counter)
    for exp, pred in rows:
        m[exp][pred] += 1
    return m


def _format_matrix(m: Dict[str, Counter], labels: List[str]) -> str:
    # simple fixed-width table
    colw = 16
    header = "expected\\pred".ljust(colw) + "".join(l.ljust(colw) for l in labels)
    lines = [header]
    for e in labels:
        row = e.ljust(colw)
        for p in labels:
            row += str(m.get(e, Counter()).get(p, 0)).ljust(colw)
        lines.append(row)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="old.py", help="Path to classifier module file (default: old.py)")
    ap.add_argument("--fn", default=None, help="Classifier function name (optional). If omitted, auto-detect.")
    ap.add_argument("--dataset", default="test_rich_mixed_300.json", help="Path to dataset JSON.")
    ap.add_argument("--max-errors", type=int, default=20, help="How many misclassified samples to print.")
    ap.add_argument("--fail-under", type=float, default=None, help="If set, exit with code 3 when accuracy < threshold.")
    ap.add_argument("--verbose", action="store_true", help="Print per-sample output (noisy).")
    args = ap.parse_args(argv)

    module_path = Path(args.module).resolve()
    dataset_path = Path(args.dataset).resolve()

    try:
        mod = _load_module_from_path(module_path)
        clf = _pick_classifier_fn(mod, args.fn)
    except Exception as ex:
        print(f"[ERROR] Failed to load classifier: {ex}", file=sys.stderr)
        return 2

    try:
        dataset = _load_dataset(dataset_path)
    except Exception as ex:
        print(f"[ERROR] Failed to load dataset: {ex}", file=sys.stderr)
        return 2

    total = 0
    correct = 0
    pairs: List[Tuple[str, str]] = []
    errors: List[Dict[str, Any]] = []

    for row in dataset:
        text = str(row.get("text") or "")
        expected = _norm_kind(row.get("kind"))
        if expected not in ALLOWED_KINDS:
            expected = "unknown"

        try:
            result = clf(text)
        except Exception as ex:
            pred, conf = "unknown", 0.0
            errors.append({
                "id": row.get("id"),
                "expected": expected,
                "predicted": pred,
                "confidence": conf,
                "error": f"classifier_exception: {type(ex).__name__}: {ex}",
                "text_preview": text[:160],
            })
            pairs.append((expected, pred))
            total += 1
            continue

        pred, conf = _extract_kind_conf(result)
        if pred not in ALLOWED_KINDS:
            pred = "unknown"

        ok = (pred == expected)
        total += 1
        correct += 1 if ok else 0
        pairs.append((expected, pred))

        if args.verbose:
            rid = row.get("id") or f"row{total}"
            print(f"{rid}: expected={expected} predicted={pred} conf={conf:.3f}")

        if not ok and len(errors) < args.max_errors:
            errors.append({
                "id": row.get("id"),
                "expected": expected,
                "predicted": pred,
                "confidence": conf,
                "text_preview": text[:220],
            })

    acc = (correct / total) if total else 0.0
    labels = ["dotnet", "sql", "dotnet_with_sql", "unknown"]
    m = _confusion_matrix(pairs)

    print(f"module:  {module_path.name}")
    print(f"fn:      {getattr(clf, '__name__', str(clf))}")
    print(f"dataset: {dataset_path.name}")
    print(f"total:   {total}")
    print(f"correct: {correct}")
    print(f"accuracy:{acc:.4f}")
    print("")
    print("confusion matrix:")
    print(_format_matrix(m, labels))

    if errors:
        print("")
        print(f"misclassified samples (up to {args.max_errors}):")
        for e in errors:
            rid = e.get("id")
            print(f"- id={rid} expected={e['expected']} predicted={e['predicted']} conf={e['confidence']:.3f}")
            if "error" in e:
                print(f"  error: {e['error']}")
            print(f"  preview: {e['text_preview'].replace(chr(10), ' ')[:220]}")

    if args.fail_under is not None and acc < float(args.fail_under):
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
