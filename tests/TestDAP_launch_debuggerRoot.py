"""
Test lldb-dap launch request.
"""

import os

from lldbsuite.test import lldbplatformutil
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_debuggerRoot(DAPTestCaseBase):
    """
    Tests the "debuggerRoot" will change the working directory of
    the lldb-dap debug adapter.
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
        program_parent_dir = os.path.realpath(os.path.dirname(os.path.dirname(program)))

        var = "%cd%" if lldbplatformutil.getHostPlatform() == "windows" else "$PWD"
        init_commands = [f"platform shell echo cwd = {var}"]

        session = self.build_and_create_session()
        process_event = session.launch(
            LaunchArgs(
                program=program,
                debuggerRoot=program_parent_dir,
                initCommands=init_commands,
            )
        )
        session.verify_process_exited(after=process_event)

        output = session.get_console()
        self.assertTrue(output and len(output) > 0, "expect console output")

        prefix = "cwd = "
        cwd_lines = [line for line in output.splitlines() if line.startswith(prefix)]
        self.assertEqual(
            len(cwd_lines), 1, "expected exactly one cwd line in console output"
        )
        self.assertEqual(
            cwd_lines[0].strip()[len(prefix) :],
            program_parent_dir,
            f"lldb-dap working dir mismatch: expected '{program_parent_dir}', "
            f"got '{cwd_lines[0]}'",
        )
