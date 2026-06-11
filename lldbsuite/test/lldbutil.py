import os
import time


def append_to_process_working_directory(test, *paths):
    return os.path.join(test.getBuildDir(), *paths)


def read_file_on_target(test, local: str):
    with open(local, "r") as f:
        return f.read()


def wait_for_file_on_target(testcase, file_path: str):
    timeout_seconds = 600 if "ASAN_OPTIONS" in os.environ else 120
    sleep_interval_seconds = 0.5
    deadline_seconds = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline_seconds:
        command = f"ls {file_path}"
        err, retcode, _ = testcase.run_platform_command(command)
        if err == "" and retcode == 0:
            return read_file_on_target(testcase, file_path)

        time.sleep(sleep_interval_seconds)

    testcase.fail(f"File {file_path} not found after {timeout_seconds} seconds.")
