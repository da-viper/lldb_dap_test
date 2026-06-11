"""
Test lldb-dap launch request.
"""

from lldbsuite.test.tools.lldb_dap.dap_types import Console, LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_launch_invalid_launch_commands_and_console(DAPTestCaseBase):
    """
    Tests launching with launch commands in an integrated terminal.
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

        err_response = session.send_request(
            LaunchArgs(
                program=program,
                launchCommands=["a b c"],
                console=Console.INTEGRATED_TERMINAL,
            )
        ).error()
        error_msg = self.expect_not_none(
            err_response.body and err_response.body.error,
            "expected an error message in the launch response",
        )
        self.assertTrue(error_msg.showUser, "expected showUser=true")
        self.assertIn(
            "'launchCommands' and non-internal 'console' are mutually exclusive",
            error_msg.format,
        )
