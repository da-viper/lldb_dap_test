from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


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
        process_event = session.launch(LaunchArgs(program, args=args))
        session.verify_process_exited(after=process_event)

        # Now get the STDOUT and verify our arguments got passed correctly
        output = session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program output")
        lines = output.splitlines()
        # Skip the first argument that contains the program name
        lines.pop(0)
        # Make sure arguments we specified are correct
        for i, arg in enumerate(args):
            quoted_arg = '"%s"' % (arg)
            self.assertIn(
                quoted_arg,
                lines[i],
                'arg[%i] "%s" not in "%s"' % (i + 1, quoted_arg, lines[i]),
            )
