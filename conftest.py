import os
from collections import defaultdict
from typing import Dict


def strtobool(val: str) -> bool:
    """Convert a string representation of truth to a bool following LLVM's CLI argument parsing."""

    val = val.lower()
    if val in ["false", "0"]:
        return False
    return True


# appends [SERVER] if in server mode.
def pytest_collection_modifyitems(session, config, items):
    # Assumes it is the same for all test
    is_server = strtobool(os.environ.get("LLDBDAP_RUN_AS_SERVER", "false"))

    if is_server:
        prefix = f"[SERVER]"
        for item in items:
            # Modify the nodeid (how pytest internally tracks and reports the test)
            if not item._nodeid.startswith(prefix):
                item._nodeid = f"{prefix} {item._nodeid}"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print the slowest test files alongside pytest's per-function durations.

    Reuses `--durations=N` to decide how many files to list. Sums setup +
    call + teardown durations across every test in each file.
    """
    n = config.option.durations or 0
    if not n:
        return

    by_file: Dict[str, float] = defaultdict(float)
    for stat_list in terminalreporter.stats.values():
        for rep in stat_list:
            if not hasattr(rep, "duration"):
                continue
            # nodeid: "tests/TestFoo.py::TestClass::test_method"
            file_key = rep.nodeid.split("::", 1)[0]
            by_file[file_key] += rep.duration

    if not by_file:
        return

    terminalreporter.write_sep("=", f"slowest {n} test files")
    for key, total in sorted(by_file.items(), key=lambda kv: -kv[1])[:n]:
        terminalreporter.write_line(f"{total:>8.2f}s  {key}")
