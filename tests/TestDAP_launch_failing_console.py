"""
Test lldb-dap launch request.
"""

from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_failing_console(DAPTestCaseBase):
    """
    Tests launching in console with an invalid terminal type.
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
        # No build needed: the launch request should be rejected during arg
        # validation, before lldb-dap touches the program path.
        session = self.create_session()
        session.initialize_sequence(session.initialize_args)

        launch_args = LaunchArgs(program=program, console="invalid")
        err_response = session.send_request(launch_args).error()
        error_msg = self.expect_not_none(
            err_response.body and err_response.body.error,
            "expected an error message in the launch response",
        )
        self.assertTrue(error_msg.showUser, "expected showUser=true")
        self.assertRegex(
            error_msg.format,
            r"unexpected value, expected 'internalConsole', 'integratedTerminal' or 'externalTerminal' at arguments.console",
        )
