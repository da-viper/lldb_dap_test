"""
Test lldb-dap RestartRequest.
"""

from lldb_dap.dap_types import LaunchArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number


class TestDAP_restart(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <stdio.h>

int main(int argc, char const *argv[], char const *envp[]) {
  int i = 0;
  printf("Do something\n"); // breakpoint A
  printf("Do something else\n");
  i = 1234;
  return 0; // breakpoint B
}
"""
    IS_C = True

    @skipIfWindows
    def test_basic_functionality(self):
        """
        Tests the basic restarting functionality: set two breakpoints in
        sequence, restart at the second, check that we hit the first one.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        line_A = line_number("main.c", "// breakpoint A")
        line_B = line_number("main.c", "// breakpoint B")

        with session.configure(LaunchArgs(program)) as ctx:
            [bp_A, bp_B] = session.resolve_source_breakpoints(
                "main.c", [line_A, line_B]
            )

        # Verify we hit A, then B.
        session.verify_stopped_on_breakpoint([bp_A], after=ctx.process_event())
        stop_event = session.continue_to_breakpoint(bp_B)

        # Make sure i has been modified from its initial value of 0.
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        i_val = thread_ctx.top_frame().locals["i"]
        self.assertEqual(
            i_val.value_as_int, 1234, "i != 1234 after hitting breakpoint B"
        )

        # Restart then check we stop back at A and program state has been reset.
        last_response = session.last_response()
        resp = session.do_restart()
        self.assertTrue(resp.success)

        stop_event = session.verify_stopped_on_breakpoint([bp_A], after=last_response)
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        i_val = thread_ctx.top_frame().locals["i"]
        self.assertEqual(
            i_val.value_as_int, 0, "i != 0 after hitting breakpoint A on restart"
        )

    @skipIfWindows
    def test_stopOnEntry(self):
        """
        Check that the stopOnEntry setting is still honored after a restart.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        with session.configure(LaunchArgs(program, stopOnEntry=True)) as ctx:
            [bp_main] = session.resolve_function_breakpoints(["main"])

        session.verify_stopped_on_entry(after=ctx.process_event())

        # Then, if we continue, we should hit the breakpoint at main.
        bp_stop_event = session.continue_to_breakpoint(bp_main)

        # Restart and check that we still get a stopped event before reaching
        # main.
        resp = session.do_restart()
        self.assertTrue(resp.success)
        session.verify_stopped_on_entry(after=bp_stop_event)

    @skipIfWindows
    def test_arguments(self):
        """
        Tests that lldb-dap will use updated launch arguments included
        with a restart request.
        """
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        line_A = line_number("main.c", "// breakpoint A")

        with session.configure(LaunchArgs(program)) as ctx:
            [bp_A] = session.resolve_source_breakpoints("main.c", [line_A])

        # Verify we hit A, then B.
        stop_event = session.verify_stopped_on_breakpoint(
            [bp_A], after=ctx.process_event()
        )

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        argc_val = thread_ctx.top_frame().locals["argc"]
        # We don't set any arguments in the initial launch request, so argc
        # should be 1.
        self.assertEqual(argc_val.value_as_int, 1, "argc != 1 before restart")

        last_response = session.last_response()
        # Restart with some extra 'args' and check that the new argc reflects
        # the updated launch config.
        resp = session.do_restart(LaunchArgs(program, args=["a", "b", "c", "d"]))
        self.assertTrue(resp.success)

        stop_event = session.verify_stopped_on_breakpoint([bp_A], after=last_response)
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        argc_val = thread_ctx.top_frame().locals["argc"]
        self.assertEqual(argc_val.value_as_int, 5, "argc != 5 after restart")

        session.continue_to_exit()
