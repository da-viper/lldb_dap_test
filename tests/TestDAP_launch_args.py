"""
Test lldb-dap launch request.
"""

from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_launch_args(DAPTestCaseBase):
    """
    Tests launch of a simple program with arguments
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

    def test(self):
        program = self.getBuildArtifact("a.out")
        args = ["one", "with space", "'with single quotes'", '"with double quotes"']
        session = self.build_and_create_session()
        session.launch(LaunchArgs(program=program, args=args))
        session.verify_process_exited()

        output = session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program output")
        lines = output.splitlines()
        # Skip the first argument that contains the program name.
        lines.pop(0)
        # Make sure arguments we specified are correct.
        args_and_lines = zip(args, lines)
        for i, (arg, line) in enumerate(args_and_lines, start=1):
            quoted_arg = f'"{arg}"'
            self.assertIn(
                quoted_arg,
                line,
                f'arg[{i}] "{arg}" not in {line!r}',
            )
