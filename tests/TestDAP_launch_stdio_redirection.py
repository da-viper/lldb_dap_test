"""
Test lldb-dap launch request.
"""

import tempfile

from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_stdio_redirection(DAPTestCaseBase):
    """
    Test stdio redirection.
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
        session = self.build_and_create_session()

        with tempfile.NamedTemporaryFile("rt") as f:
            process_event = session.launch(
                LaunchArgs(program=program, stdio=[None, f.name])
            )
            session.verify_process_exited(after=process_event)
            lines = f.readlines()
            self.assertIn(
                program, lines[0], "make sure program path is in first argument"
            )
