from __future__ import annotations

import argparse
from pathlib import Path

from .converter import puml_to_xmi


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert PlantUML to XMI (EA import).")
    parser.add_argument("input", help="Path to .puml or .txt file containing @startuml block")
    parser.add_argument("-o", "--output", help="Output .xmi path", required=True)
    parser.add_argument("--model-name", default="PUML Model", help="Model name in XMI")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"Input not found: {src}")

    text = src.read_text(encoding="utf-8")
    xmi = puml_to_xmi(text, model_name=args.model_name)

    Path(args.output).write_text(xmi, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
