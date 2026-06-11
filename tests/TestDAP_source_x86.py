"""
Test lldb-dap stack trace containing x86 assembly
"""

from lldbsuite.test import lldbplatformutil
from lldbsuite.test.decorators import skipUnlessArch, skipUnlessPlatform
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_stacktrace_x86(DAPTestCaseBase):
    TEST_PROGRAM = r"""#include <stdio.h>

__attribute__((nodebug)) int no_branch_func(void) {
  int result = 0;

  __asm__ __volatile__("movl $0, %%eax;" // Assembly start
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "incl %%eax;"
                       "movl %%eax, %0;" // Assembly end
                       : "=r"(result)
                       :
                       : "%eax");

  return result;
}

int main(void) {
  int result = no_branch_func(); // Break here
  printf("Result: %d\n", result);
  return 0;
}
"""
    IS_C = True

    @skipUnlessArch("x86_64")
    @skipUnlessPlatform(["linux"] + lldbplatformutil.getDarwinOSTriples())
    def test_stacktrace_x86(self):
        """
        Tests that lldb-dap steps through correctly and the source lines are correct in x86 assembly.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        launch_args = LaunchArgs(
            program,
            initCommands=[
                "settings set target.process.thread.step-in-avoid-nodebug false"
            ],
        )
        with session.configure(launch_args) as ctx:
            source = "main.c"
            [breakpoint_ids] = session.resolve_source_breakpoints(
                source, [line_number(source, "// Break here")]
            )

        stop_event = session.verify_stopped_on_breakpoint(
            breakpoint_ids, after=ctx.process_event
        )

        thread_ctx = session.thread_context_from(stop_event)
        thread_ctx.step_in()

        frame = thread_ctx.top_frame().frame
        self.assertEqual(
            frame.name,
            "no_branch_func",
            "verify we are in the no_branch_func function",
        )

        self.assertEqual(frame.line, 1, "verify we are at the start of the function")
        minimum_assembly_lines = (
            line_number(source, "Assembly end")
            - line_number(source, "Assembly start")
            + 1
        )
        self.assertLessEqual(
            10,
            minimum_assembly_lines,
            "verify we have a reasonable number of assembly lines",
        )

        for i in range(2, minimum_assembly_lines):
            thread_ctx.step_in()
            top_frame = thread_ctx.top_frame().frame
            self.assertEqual(
                top_frame.name,
                "no_branch_func",
                "verify we are still in the no_branch_func function",
            )
            self.assertEqual(
                top_frame.line,
                i,
                f"step in should advance a single line in the function to {i}",
            )
