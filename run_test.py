#!/usr/bin/env python3


import sys
import os
import unittest
import argparse
from pathlib import Path
from lldb_dap import configuration

sys.dont_write_bytecode = True


class DAPTestResult(unittest.TextTestResult):
    def getDescription(self, test: unittest.TestCase):
        return str(test)

    def addSuccess(self, test: unittest.TestCase):
        if self.showAll:
            self.stream.writeln("PASS")
        elif self.dots:
            self.stream.write(".")
            self.stream.flush()


def main():
    parser = argparse.ArgumentParser(description="Run DAP tests")
    dap_path = str(Path.home() / "Dev/contribute/llvm-build/release/bin/lldb-dap")
    if sys.platform == "darwin":
        dap_path = "/Volumes/workspace/Dev/llvm-build/release/bin/lldb-dap"
    parser.add_argument(
        "--adapter-path",
        default=os.getenv("DAP_ADAPTER_PATH", dap_path),
        help="Path to the debug adapter executable",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=os.getenv("DAP_TIMEOUT", 30.0),
        help="Timeout for DAP operations in seconds",
    )
    parser.add_argument(
        "--verbosity",
        type=int,
        default=2,
        choices=[0, 1, 2],
        help="Test output verbosity",
    )
    parser.add_argument("--pattern", default="Test*.py", help="Test file pattern")
    parser.add_argument("--failfast", action="store_true", help="Stop on first failure")
    parser.add_argument(
        "tests",
        nargs="*",
        help="Specific tests to run (e.g., TestDAP_module, test.)",
    )

    args = parser.parse_args()
    configuration.test_build_dir = Path(os.getcwd()) / "builds"

    # Set environment variables for tests
    os.environ["DAP_ADAPTER_PATH"] = args.adapter_path
    os.environ["DAP_TIMEOUT"] = str(args.timeout)

    # Discover and run tests
    if args.tests:
        # Run specific tests
        def to_module(name: str):
            name = name.replace(".", "/")
            base_name = Path(name).stem
            return f"tests.{base_name}"

        test_modules = list(map(to_module, args.tests))
        suite = unittest.TestLoader().loadTestsFromNames(test_modules)
    else:
        # Discover all tests

        start_dir = Path(__file__).parent / "tests"
        suite = unittest.TestLoader().discover(
            start_dir=str(start_dir), pattern=args.pattern
        )

    # Run tests
    result_c = DAPTestResult
    runner = unittest.TextTestRunner(
        verbosity=args.verbosity, failfast=args.failfast, resultclass=result_c
    )
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
