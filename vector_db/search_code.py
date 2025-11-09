import os
import sys
import json
import torch
import readline  # keeps readline features on Linux terminals
from unittest.mock import Mock

# -----------------------------------------------------------------------------
# Lightweight mocks for optional modules some HF models try to import.
# They are not used here but prevent unnecessary import errors.
# -----------------------------------------------------------------------------
torchvision_mock = Mock()
torchvision_mock.__spec__ = Mock()
torchvision_mock.__version__ = "0.18.0"
sys.modules["torchvision"] = torchvision_mock
sys.modules["transformers.image_utils"] = Mock()
sys.modules["transformers.image_transforms"] = Mock()

# -----------------------------------------------------------------------------
# Backend search (FAISS + formatting)
# -----------------------------------------------------------------------------
from common.search_engine import query_faiss, format_results_as_text

# -----------------------------------------------------------------------------
# Config (kept for compatibility if other parts rely on it)
# -----------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
base_dir = os.path.join(script_dir, "..")
config_path = os.path.join(base_dir, "config.json")
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

# -----------------------------------------------------------------------------
# Translator EN↔PL (we translate PL → EN for search queries)
# -----------------------------------------------------------------------------
from transformers import MarianMTModel, MarianTokenizer

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
translator_model_name = "Helsinki-NLP/opus-mt-pl-en"
translator_tokenizer = MarianTokenizer.from_pretrained(translator_model_name)
translator_model = MarianMTModel.from_pretrained(translator_model_name).to(device)


def translate_query(query: str) -> str:
    """
    Translate PL → EN using MarianMT.
    """
    inputs = translator_tokenizer(query, return_tensors="pt", padding=True, truncation=True).to(device)
    outputs = translator_model.generate(**inputs)
    return translator_tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]


def clear_console() -> None:
    """
    Clear terminal screen on Windows/Linux/macOS.
    """
    os.system("cls" if os.name == "nt" else "clear")


def run_cli() -> None:
    """
    Interactive CLI:
    - reads a query (type 'exit' to quit),
    - translates PL→EN,
    - runs FAISS search on the translated query,
    - prints formatted results,
    - keeps a simple in-memory history.
    """
    query_history: list[str] = []

    while True:
        try:
            query = input("\nEnter query (or 'exit' to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if query.lower() == "exit":
            break
        if not query:
            continue

        query_translated = translate_query(query)
        query_history.append(f"{query} -> {query_translated}")

        clear_console()
        print(f"\nSearching for: {query_translated} (original: {query})\n")

        results = query_faiss(query_translated)
        print(format_results_as_text(results))

        # Free GPU memory between queries (no-op on CPU)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    print("\nSearch history:")
    for q in query_history:
        print(f"- {q}")

    print("\nFinished.")
    

if __name__ == "__main__":
    run_cli()
