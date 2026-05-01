from dataclasses import is_dataclass
import time
from typing import cast
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import (
    Event,
    ExitedEvent,
    LaunchArgs,
    OutputEvent,
    OutputCategory,
)


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
        test_program = self.create_and_compile_file(self.TEST_PROGRAM)

        args = ["one", "with space", "'with single quotes'", '"with double quotes"']
        launch_args = LaunchArgs(program=test_program, args=args)
        process_event, _ = self.session.launch_using_config(launch_args)
        self.session.verify_process_exited(after=process_event)

        output = self.session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program output")
        output = output.splitlines()
        lines = output
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
