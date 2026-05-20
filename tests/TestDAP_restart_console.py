"""
Test lldb-dap RestartRequest.
"""


import unittest

from lldb_dap.dap_types import Console, LaunchArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.decorators import (
    expectedFailureWindows,
    skipIf,
    skipIfAsan,
    skipIfBuildType,
    skipIfWindows,
)
from lldbsuite.test.lldbtest import line_number


@skipIfBuildType(["debug"])
class TestDAP_restart_console(DAPTestCaseBase):
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

    @skipIfAsan
    @expectedFailureWindows
    @skipIf(oslist=["linux"], archs=["arm$"])  # Always times out on buildbot
    def test_basic_functionality(self):
        """
        Test basic restarting functionality when the process is running in
        a terminal.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        launch_args = LaunchArgs(program, console=Console.INTEGRATED_TERMINAL)
        with session.configure(launch_args) as ctx:
            line_A = line_number("main.c", "// breakpoint A")
            line_B = line_number("main.c", "// breakpoint B")

            [bp_A, bp_B] = session.resolve_source_breakpoints(
                "main.c", [line_A, line_B]
            )

        # Verify we hit A, then B.
        session.verify_stopped_on_breakpoint([bp_A], after=ctx.process_event())
        resp = session.do_continue()
        stop_event = session.verify_stopped_on_breakpoint([bp_B], after=resp)

        # Make sure i has been modified from its initial value of 0.
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        self.assertEqual(
            thread_ctx.top_frame().locals["i"].value_as_int,
            1234,
            "i != 1234 after hitting breakpoint B",
        )

        last_response = session.last_response()
        # Restart.
        session.do_restart()

        # Finally, check we stop back at A and program state has been reset.
        stop_event = session.verify_stopped_on_breakpoint([bp_A], after=last_response)
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        i_val = thread_ctx.top_frame().locals["i"].value_as_int
        self.assertEqual(i_val, 0, "i != 0 after hitting breakpoint A on restart")

        # Check breakpoint B
        resp = session.do_continue()
        stop_event = session.verify_stopped_on_breakpoint([bp_B], after=resp)
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        self.assertEqual(
            thread_ctx.top_frame().locals["i"].value_as_int,
            1234,
            "i != 1234 after hitting breakpoint B",
        )
        session.continue_to_exit()

    @skipIfAsan
    @expectedFailureWindows
    @skipIf(oslist=["linux"], archs=["arm$"])  # Always times out on buildbot
    def test_stopOnEntry(self):
        """
        Check that stopOnEntry works correctly when using console.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        launch_args = LaunchArgs(
            program, console=Console.INTEGRATED_TERMINAL, stopOnEntry=True
        )

        with session.configure(launch_args) as ctx:
            [bp_main] = session.resolve_function_breakpoints(["main"])
        session.verify_stopped_on_entry(after=ctx.process_event())

        # Then, if we continue, we should hit the breakpoint at main.
        stop_event = session.continue_to_any_breakpoint([bp_main])

        # Restart and check that we still get a stopped event before reaching
        # main.
        session.do_restart()
        session.verify_stopped_on_entry(after=stop_event)

        # continue to main
        session.continue_to_any_breakpoint([bp_main])
        session.continue_to_exit()

    @skipIfWindows
    @unittest.skip(
        "# (TODO) newly added for some reason the exit code is wrong when are runInTerminal"
    )
    def test_arguments(self):
        """
        Tests that lldb-dap will use updated launch arguments included
        with a restart request.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        launch_args = LaunchArgs(program, console=Console.INTEGRATED_TERMINAL)
        with session.configure(launch_args) as ctx:
            line_A = line_number("main.c", "// breakpoint A")
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
