"""
Test lldb-dap launch request.
"""
import os

from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_cwd(DAPTestCaseBase):
    """
    Tests the default launch of a simple program with a current working
    directory.
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
        program_parent_dir = os.path.realpath(os.path.dirname(os.path.dirname(program)))
        session = self.build_and_create_session()
        session.launch(LaunchArgs(program=program, cwd=program_parent_dir))
        session.verify_process_exited()

        # Now get the STDOUT and verify our program's working directory is correct
        output = session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program output")

        lines = output.splitlines()
        cwd_lines = [line for line in lines if line.startswith('cwd = "')]
        self.assertEqual(len(cwd_lines), 1, "verified program working directory")
        cwd_line = cwd_lines[0]

        quote_path = f'"{program_parent_dir}"'
        self.assertIn(
            quote_path,
            cwd_line,
            f"working directory '{program_parent_dir}' not in '{cwd_line}'",
        )
