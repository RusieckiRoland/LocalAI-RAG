# main.py — prosty CLI: tylko --pretty, zawsze emit RAG JSON
import argparse
import json

from .api import summarize_tsql
from .emit import make_compact  # stały tryb "rag"

def main():
    ap = argparse.ArgumentParser(
        prog="tsql_summarizer",
        description="T-SQL summarizer pod RAG. Domyślnie wypisuje RAG JSON; --pretty tylko formatuje wyjście."
    )
    ap.add_argument("tsql_file", help="Ścieżka do pliku .sql")
    ap.add_argument(
        "--pretty",
        action="store_true",
        help="Wypisz JSON w formie sformatowanej (pretty-print)"
    )
    args = ap.parse_args()

    with open(args.tsql_file, "r", encoding="utf-8") as f:
        tsql = f.read()

    # 1) pełna analiza
    payload = summarize_tsql(tsql)

    # 2) stały tryb emisji: RAG
    out = make_compact(payload)  # bez żadnych trybów / minify

    if args.pretty:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
