import os
import shutil

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap import lldb_dap_testcase
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs


class TestDAP_InstructionBreakpointTestCase(lldb_dap_testcase.DAPTestCaseBase):
    NO_DEBUG_INFO_TESTCASE = True

    TEST_PROGRAM = r"""#include <cstdio>
#include <unistd.h>

int function(int x) {

  if (x == 0) // breakpoint 1
    return x;

  if ((x % 2) != 0)
    return x;
  else
    return function(x - 1) + x;
}

int main(int argc, char const *argv[]) {
  int n = function(2);
  return n;
}

"""

    def setUp(self):
        super().setUp()

        self.main_basename = "main-copy.cpp"
        self.main_path = os.path.realpath(self.getBuildArtifact(self.main_basename))

    def build(self):
        # TODO: START -- this is not needed when we port
        main_cpp = self.create_file(self.TEST_PROGRAM, "main.cpp")
        shutil.copy(main_cpp, self.main_path)
        self.create_test_program_with_name(self.main_path)
        # end make

    @skipIfWindows
    def test_instruction_breakpoint(self):
        self.build()
        self.instruction_breakpoint_test()

    def instruction_breakpoint_test(self):
        """Sample test to ensure SBFrame::Disassemble produces SOME output"""
        # Create a target by the debugger.

        program = self.getBuildArtifact("a.out")
        session = self.create_session()
        main_line = line_number("main.cpp", "breakpoint 1")

        with session.configure(LaunchArgs(program)) as ctx:
            # Set source breakpoint 1
            response = session.set_source_breakpoints(self.main_path, [main_line])
            breakpoints = response.body.breakpoints
            self.assertEqual(len(breakpoints), 1)
            breakpoint = breakpoints[0]
            self.assertEqual(
                breakpoint.line, main_line, "incorrect breakpoint source line"
            )
            self.assertTrue(breakpoint.verified, "breakpoint is not verified")
            breakpoint_source = self.expect_not_none(breakpoint.source)
            self.assertEqual(
                self.main_basename, breakpoint_source.name, "incorrect source name"
            )
            self.assertEqual(
                self.main_path, breakpoint_source.path, "incorrect source file path"
            )
            other_breakpoint_id = self.expect_not_none(breakpoint.id)

        # Continue and then verify the breakpoint
        stop_event = session.verify_stopped_on_breakpoint(
            other_breakpoint_id, after=ctx.process_event
        )

        # now we check the stack trace making sure that we got mapped source paths
        thread_ctx = session.thread_context_from(stop_event)
        top_frame_ctx = thread_ctx.top_frame()
        top_frame = top_frame_ctx.frame

        frame_source = self.expect_not_none(top_frame.source)
        self.assertEqual(frame_source.name, self.main_basename, "incorrect source name")
        self.assertEqual(
            frame_source.path, self.main_path, "incorrect source file path"
        )

        # Check disassembly view
        disassembled_instructions = top_frame_ctx.disassemble()
        first_instruction = disassembled_instructions[0]
        self.assertEqual(
            first_instruction.address,
            top_frame.instructionPointerReference,
            "current breakpoint reference is not in the disassembly view",
        )

        # Get next instruction address to set instruction breakpoint
        next_instruction = disassembled_instructions[1]
        next_address = next_instruction.address

        self.assertGreater(len(next_address), 2)
        self.assertNotEqual(next_instruction.presentationHint, "invalid")

        bp_response = session.set_instruction_breakpoints([next_address])
        inst_breakpoint, *_ = bp_response.body.breakpoints

        self.assertEqual(
            inst_breakpoint.instructionReference,
            next_address,
            "Instruction breakpoint has not been resolved or failed to relocate the instruction breakpoint",
        )

        inst_breakpoint_id = self.expect_not_none(inst_breakpoint.id)
        session.continue_to_breakpoint(inst_breakpoint_id)

        # Clear breakpoints that are set.
        session.set_source_breakpoints(self.main_path, [])
        session.set_instruction_breakpoints([])

        session.continue_to_exit(3)
