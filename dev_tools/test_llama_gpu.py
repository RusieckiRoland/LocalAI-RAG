# File: dev_tools/test_llama_gpu.py
from __future__ import annotations

"""
Lightweight smoke test for llama-cpp model loading and a single completion.

- Reads `config.json` from the project root (one level above this file's parent).
- Uses key `model_path_analysis` for the model path (relative or absolute).
- Tries to load with GPU layers first; falls back to CPU if that fails.
- Prints timing and the first completion text.

All logs and comments are in English for public repo consistency.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from typing import Any, Dict

from llama_cpp import Llama


def _parse_bool(val: Any, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _load_config(base_dir: Path) -> Dict[str, Any]:
    cfg_path = base_dir / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.json not found at: {cfg_path}")
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)


def _resolve_model_path(base_dir: Path, cfg: Dict[str, Any], key: str = "model_path_analysis") -> str:
    raw = cfg.get(key)
    if not raw or not isinstance(raw, str):
        raise KeyError(f'Missing or invalid "{key}" in config.json')

    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    if not p.exists():
        raise FileNotFoundError(f"Model file not found: {p}")
    return str(p)


def _create_model(model_path: str, n_ctx: int, n_gpu_layers: int, verbose: bool) -> Llama:
    """
    Try to create a GPU-backed model first; if it fails, retry on CPU (n_gpu_layers=0).
    """
    try:
        return Llama(model_path=model_path, n_gpu_layers=n_gpu_layers, n_ctx=n_ctx, verbose=verbose)
    except Exception as e:
        logging.warning("GPU load failed (%s). Retrying on CPU...", e)
        return Llama(model_path=model_path, n_gpu_layers=0, n_ctx=n_ctx, verbose=verbose)


def main() -> int:
    # Configure logging once
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Ensure LLAMA_SET_ROWS=1, unless already set
    os.environ.setdefault("LLAMA_SET_ROWS", "1")

    # Project root is one level above this file's parent
    script_path = Path(__file__).resolve()
    base_dir = script_path.parent.parent  # repo root

    # Load config and resolve model path
    cfg = _load_config(base_dir)
    model_path = _resolve_model_path(base_dir, cfg, key="model_path_analysis")

    # Optional knobs from config (with sensible defaults)
    n_ctx = int(cfg.get("llama_ctx", 2048))
    n_gpu_layers = int(cfg.get("llama_gpu_layers", 60))
    verbose = _parse_bool(cfg.get("llama_verbose", True), default=True)

    logging.info("Loading model from: %s", model_path)
    logging.info("Settings: n_ctx=%d, n_gpu_layers=%d, verbose=%s", n_ctx, n_gpu_layers, verbose)

    t0 = time.time()
    model = _create_model(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=verbose)
    logging.info("Model loaded in %.2f s", time.time() - t0)

    # Simple prompt for a quick sanity check
    prompt = "What is the capital of France?"
    logging.info("Running a single completion...")

    t1 = time.time()
    out = model(prompt, max_tokens=64)
    dt = time.time() - t1

    # llama_cpp returns a dict with 'choices' where each choice has 'text'
    text = (out.get("choices") or [{}])[0].get("text", "")
    print(f"\nTime taken: {dt:.2f} seconds")
    print("Response:", text.strip())

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logging.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
