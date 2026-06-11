"""
Test lldb-dap launch request.
"""

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_launch_environment_with_array(DAPTestCaseBase):
    """
    Tests launch of a simple program with environment variables
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

    @skipIfWindows
    def test(self):
        program = self.getBuildArtifact("a.out")
        expected_env = [
            "NO_VALUE",
            "WITH_VALUE=BAR",
            "EMPTY_VALUE=",
            "SPACE=Hello World",
        ]

        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program=program, env=expected_env))
        session.verify_process_exited(after=process_event)

        # Now get the STDOUT and verify our arguments got passed correctly
        output = session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program output")
        lines = output.splitlines()
        # Collect environment lines.
        env_lines = [line for line in lines if line.startswith("env[")]
        # Make sure each environment variable in "env" is actually set in the
        # program environment that was printed to STDOUT
        for var in expected_env:
            found_var = any(var in line for line in env_lines)
            self.assertTrue(
                found_var,
                f'"{var}" must exist in program environment ({env_lines})',
            )
