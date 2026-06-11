"""
Test lldb-dap launch request.
"""

import os

from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_launch_shellExpandArguments_disabled(DAPTestCaseBase):
    """
    Tests the default launch of a simple program with shell expansion
    disabled.
    """

    TEST_PROGRAM = r"""
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <direct.h>
#else
#include <unistd.h>
#endif

int main(int argc, char const *argv[], char const *envp[]) {
  for (int i = 0; i < argc; ++i)
    printf("arg[%i] = \"%s\"\n", i, argv[i]);
  for (int i = 0; envp[i]; ++i)
    printf("env[%i] = \"%s\"\n", i, envp[i]);
  char *cwd = getcwd(NULL, 0);
  printf("cwd = \"%s\"\n", cwd); // breakpoint 1
  free(cwd);
  cwd = NULL;
  return 0; // breakpoint 2
}
"""
    IS_C = True

    def test(self):
        program = self.getBuildArtifact("a.out")
        program_dir = os.path.dirname(program)
        glob = os.path.join(program_dir, "*.out")
        session = self.build_and_create_session()
        process_event = session.launch(
            LaunchArgs(program=program, args=[glob], shellExpandArguments=False)
        )
        session.verify_process_exited(after=process_event)

        # Now get the STDOUT and verify our program argument is correct
        output = session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program output")
        for line in output.splitlines():
            if line.startswith("arg[1] ="):
                quote_path = f'"{glob}"'
                self.assertIn(quote_path, line, f'verify "{glob}" stayed as "{glob}"')
