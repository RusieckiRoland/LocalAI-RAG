# tests/conftest.py
from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure(config) -> None:
    # Ensure repository root is on sys.path so tests import local packages.
    repo_root = Path(__file__).resolve().parents[1]
    p = str(repo_root)
    if p not in sys.path:
        sys.path.insert(0, p)
