from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    e2e_root = Path(__file__).resolve().parent
    for item in items:
        try:
            p = Path(str(item.path)).resolve()
        except Exception:
            continue
        if e2e_root in p.parents:
            item.add_marker(pytest.mark.integration)
