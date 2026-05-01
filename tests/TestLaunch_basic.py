from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import (
    LaunchArgs,
)


class TestDAP_launch_basic(DAPTestCaseBase):
    """
    Tests the default launch of a simple program. No arguments,
    environment, or anything else is specified.
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

    def test(self):
        program = self.getBuildArtifact("a.out")
        self.build()
        process_event, _ = self.session.launch_using_config(LaunchArgs(program=program))
        self.session.verify_process_exited(after=process_event)

        # Now get the STDOUT and verify our program argument is correct
        output = self.session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program output")
        lines = output.splitlines()
        self.assertIn(program, lines[0], "make sure program path is in first argument")
