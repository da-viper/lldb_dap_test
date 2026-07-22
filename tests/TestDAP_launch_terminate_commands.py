"""
Test lldb-dap launch request.
"""

from lldbsuite.test.decorators import skipIf, skipIfNetBSD
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_terminate_commands(DAPTestCaseBase):
    """
    Tests that the "terminateCommands", that can be passed during launch,
    are run when the debugger is disconnected.
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

    @skipIfNetBSD  # Hangs on NetBSD as well
    @skipIf(archs=["arm$", "aarch64"], oslist=["linux"])
    def test(self):
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session(disconnect_automatically=False)

        terminate_commands = ["history"]
        process_event = session.launch(
            LaunchArgs(
                program=program,
                stopOnEntry=True,
                terminateCommands=terminate_commands,
            )
        )
        stop_event = session.verify_stopped_on_entry(after=process_event)
        # Once it's disconnected the console should contain the "terminateCommands".
        session.disconnect(terminateDebuggee=True)
        output = session.collect_console(after=stop_event, until=terminate_commands[0])
        session.verify_commands(
            "terminateCommands", output.seen_texts, terminate_commands
        )
