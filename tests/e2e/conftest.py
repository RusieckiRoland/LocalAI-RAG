from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Intentionally do not auto-mark e2e tests as integration.
    # This allows running tests directly without being filtered by addopts.
    return
