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


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """
    Print a short hint after unit test runs, but do not print it when integration tests were executed.
    (pytest captures stdout during tests; terminal summary is the reliable place for this hint.)
    """
    # If any executed test nodeid comes from tests/integration/, suppress the hint.
    ran_integration = False
    for reports in terminalreporter.stats.values():
        for rep in reports:
            nodeid = getattr(rep, "nodeid", "") or ""
            if nodeid.startswith("tests/integration/"):
                ran_integration = True
                break
        if ran_integration:
            break

    if not ran_integration:
        terminalreporter.write_line(
            "NOTE: if you have time, run retrieval integration tests as well: "
            "bash tools/run_retrival_integration_tests.sh"
        )
