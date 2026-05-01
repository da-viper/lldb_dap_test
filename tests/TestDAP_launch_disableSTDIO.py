"""
Test lldb-dap launch request.
"""


from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import LaunchArgs


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

    # @skipIfWindows
    def test(self):
        program = self.create_and_compile_file(self.TEST_PROGRAM)
        self.session.launch_using_config(LaunchArgs(program=program, disableSTDIO=True))
        self.session.verify_process_exited()

        # Now get the STDOUT and verify our program argument is correct
        output = self.session.get_stdout()
        self.assertEqual(output, "", "expect no program output")
