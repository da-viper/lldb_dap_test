"""
Test lldb-dap launch request.
"""

import os
import tempfile

from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.tools.lldb_dap.utils import DebugAdapterOptions


class TestDAP_launch_no_lldbinit_flag(DAPTestCaseBase):
    """
    Test that the --no-lldbinit flag prevents sourcing .lldbinit files.
    """

    USE_DEFAULT_DEBUG_ADAPTER = False
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
        # Create a temporary .lldbinit file in the home directory
        with tempfile.TemporaryDirectory() as temp_home:
            lldbinit_path = os.path.join(temp_home, ".lldbinit")

            # Write a command to the .lldbinit file that would set a unique setting
            with open(lldbinit_path, "w") as f:
                f.write("settings set stop-disassembly-display never\n")
                f.write("settings set target.x86-disassembly-flavor intel\n")

            # Build, then spin up a debug adapter with HOME pointing at the
            # temp dir and the --no-lldbinit flag.
            self.build()
            program = self.getBuildArtifact("a.out")
            adapter = self.create_stdio_debug_adapter(
                DebugAdapterOptions(
                    env={"HOME": temp_home},
                    args=["--no-lldbinit"],
                )
            )
            session = self.create_session(adapter=adapter)

            # Use initCommands to check if .lldbinit was sourced
            initCommands = ["settings show stop-disassembly-display"]
            process_event = session.launch(
                LaunchArgs(program=program, initCommands=initCommands)
            )
            session.verify_process_exited(after=process_event)

            # Get console output to verify the setting was NOT set from .lldbinit
            output = session.get_console()
            self.assertTrue(output and len(output) > 0, "expect console output")

            # Verify the setting has default value, not "never" from .lldbinit
            self.assertNotIn(
                "never",
                output,
                "Setting should have default value when --no-lldbinit is used",
            )

            # Verify the initCommands were executed
            session.verify_commands("initCommands", output, initCommands)
