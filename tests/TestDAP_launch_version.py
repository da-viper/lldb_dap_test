import unittest
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number
from lldb_dap.dap_types import LaunchArgs


# TODO: fix the alias for $__version
class TestDAP_launch_version(DAPTestCaseBase):
    """
    Tests that "initialize" response contains the "version" string the same
    as the one returned by "version" command.
    """

    TEST_PROGRAM = r"""
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char const *argv[], char const *envp[]) {
  printf("hello world\n"); // breakpoint 1
  int av = 20;
  int other = 32;
  return 0; // breakpoint 2
}

"""

    def test(self):
        source = str(self.test_dir / "main.cpp")
        program = self.create_and_compile_file(self.TEST_PROGRAM, filename=source)
        session = self.session

        session.launch_using_config(LaunchArgs(program=program, stopOnEntry=True))

        version_eval_output = session.evaluate("`version", context="repl").result
        version_string = session.capabilities().lldb_version or ""

        self.assertEqual(
            version_eval_output.splitlines(),
            version_string.splitlines(),
            "version string does not match",
        )
