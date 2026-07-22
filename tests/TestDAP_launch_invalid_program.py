"""
Test lldb-dap launch request.
"""

from lldbsuite.test.tools.lldb_dap.types import InitializedEvent, LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_invalid_program(DAPTestCaseBase):
    """
    Tests launching with an invalid program.
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
}"""
    IS_C = True

    def test(self):
        program = self.getBuildArtifact("a.out")
        session = self.create_session()
        init_response = session.initialize_sequence(session.initialize_args)
        launch_handle = session.send_request(LaunchArgs(program=program))
        session.wait_for_event(InitializedEvent, after=init_response)
        session.configuration_done().error()

        err_response = launch_handle.error()
        error_msg = self.expect_not_none(
            err_response.body and err_response.body.error,
            "expected an error message in the launch response",
        )
        self.assertEqual(error_msg.format, f"'{program}' does not exist")
