"""
Test lldb-dap launch request.
"""


from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_disableSTDIO(DAPTestCaseBase):
    """
    Tests the default launch of a simple program with STDIO disabled.
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

    @skipIfWindows
    def test(self):
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        session.launch(LaunchArgs(program=program, disableSTDIO=True))
        session.verify_process_exited()

        # Now get the STDOUT and verify our program argument is correct
        output = session.get_stdout()
        self.assertEqual(output, "", "expect no program output")
