"""
Test lldb-dap launch request.
"""

import os

from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_sourcePath(DAPTestCaseBase):
    """
    Tests the "sourcePath" will set the target.source-map.
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
        program_dir = os.path.dirname(program)
        session = self.build_and_create_session()
        process_event = session.launch(
            LaunchArgs(program=program, sourcePath=program_dir)
        )
        session.verify_process_exited(after=process_event)

        output = session.get_console()
        self.assertTrue(output and len(output) > 0, "expect console output")
        prefix = '(lldb) settings set target.source-map "." '
        found = False
        for line in output.splitlines():
            if line.startswith(prefix):
                found = True
                quoted_path = f'"{program_dir}"'
                self.assertEqual(
                    quoted_path,
                    line[len(prefix) :],
                    f"lldb-dap working dir {quoted_path} == {line[6:]}",
                )
        self.assertTrue(found, 'found "sourcePath" in console output')
