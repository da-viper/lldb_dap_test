import os


def strtobool(val: str) -> bool:
    """Convert a string representation of truth to a bool following LLVM's CLI argument parsing."""

    val = val.lower()
    if val in ["false", "0"]:
        return False
    return True


# appends [SERVER] if in server mode.
def pytest_collection_modifyitems(session, config, items):
    # Assumes it is the same for all test
    is_server = strtobool(os.environ.get("DAP_RUN_AS_SERVER", "false"))

    if is_server:
        prefix = f"[SERVER]"
        for item in items:
            # Modify the nodeid (how pytest internally tracks and reports the test)
            if not item._nodeid.startswith(prefix):
                item._nodeid = f"{prefix} {item._nodeid}"
