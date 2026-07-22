"""
Test lldb-dap output events
"""

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_output(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main() {
  // Ensure multiple partial lines are detected and sent.
  printf("abc");
  printf("def");
  printf("ghi\n");
  printf("hello world\n"); // breakpoint 1
  // Ensure the OutputRedirector does not consume the programs \0\0 output.
  char buf[] = "finally\0";
  write(STDOUT_FILENO, buf, sizeof(buf));
  return 0;
}
"""
    IS_C = True

    @skipIfWindows
    def test_output(self):
        """
        Test output handling for the running process.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session(disconnect_automatically=False)
        launch_args = LaunchArgs(
            program,
            exitCommands=[
                # Ensure that output produced by lldb itself is not consumed by the OutputRedirector.
                "?script print('out\\0\\0', end='\\r\\n', file=sys.stdout)",
                "?script print('err\\0\\0', end='\\r\\n', file=sys.stderr)",
            ],
        )
        with session.configure(launch_args) as ctx:
            source = "main.c"
            lines = [line_number(source, "// breakpoint 1")]
            breakpoint_ids = session.resolve_source_breakpoints(source, lines)

        process_event = ctx.process_event
        session.verify_stopped_on_breakpoint(breakpoint_ids, after=process_event)

        # Ensure partial messages are still sent.
        output = session.collect_stdout(after=process_event, until="abcdef")
        self.assertGreater(len(output.seen_texts), 0, "expect program stdout")

        session.continue_to_exit()

        # Disconnecting from the server to ensure any pending IO is flushed.
        session.disconnect()

        output = session.get_stdout()
        self.assertTrue(output and len(output) > 0, "expect program stdout")
        self.assertIn(
            "abcdefghi\r\nhello world\r\nfinally\0\0",
            output,
            "full stdout not found in: " + repr(output),
        )
        console = session.get_console()
        self.assertTrue(console and len(console) > 0, "expect dap messages")
        self.assertIn(
            "out\0\0\r\nerr\0\0\r\n", console, f"full console message not found"
        )
