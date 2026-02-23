def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """
    Print a short hint after unit test runs, but do not print it when integration tests were executed.
    (pytest captures stdout during tests; terminal summary is the reliable place for this hint.)
    """
    # Only treat integration as "ran" if a real test call phase executed from tests/integration/.
    # This avoids suppressing the hint when integration tests were merely collected/deselected.
    ran_integration = False

    for reports in terminalreporter.stats.values():
        for rep in reports:
            nodeid = getattr(rep, "nodeid", "") or ""

            # Only consider actual test execution reports (setup/call/teardown exist; "call" is the real one).
            when = getattr(rep, "when", None)
            if when != "call":
                continue

            if nodeid.startswith("tests/integration/"):
                ran_integration = True
                break
        if ran_integration:
            break

    if not ran_integration:
        terminalreporter.write_line(
            "NOTE: if you have time, run retrieval integration tests as well:"
        )
        terminalreporter.write_line(
            "bash tools/run_retrival_integration_tests.sh",
            blue=True,
            bold=True,
        )
