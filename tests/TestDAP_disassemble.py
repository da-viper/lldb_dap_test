"""
Test lldb-dap disassemble request
"""

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_disassemble(DAPTestCaseBase):
    IS_C = True
    TEST_PROGRAM = r"""
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

int compare_ints(const void *a, const void *b) {
  int arg1 = *(const int *)a;
  int arg2 = *(const int *)b;

  if (arg1 < arg2) // breakpoint 1
    return -1;
  if (arg1 > arg2)
    return 1;
  return 0;
}

int main(void) {
  int ints[] = {-2, 99, 0, -743, 2, INT_MIN, 4};
  int size = sizeof ints / sizeof *ints;

  qsort(ints, size, sizeof(int), compare_ints);

  for (int i = 0; i < size; i++) {
    printf("%d ", ints[i]);
  }

  printf("\n");
  return 0;
}

"""

    @skipIfWindows
    def test_disassemble(self):
        """Disassembly at the current PC returns the expected source line, and
        clearing breakpoints doesn't change the instructions."""

        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = self.getSourcePath("main.c")
        bp_line = line_number(source, "// breakpoint 1")

        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [bp_line])
        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)
        top_frame = session.thread_context_from(stop_event).top_frame()

        insts_with_bp = top_frame.disassemble()
        pc_with_bp = insts_with_bp[0]
        self.assertIsNotNone(pc_with_bp.location, "Source location missing.")
        self.assertEqual(pc_with_bp.line, bp_line, "Expects the same line number")
        self.assertTrue(pc_with_bp.instruction, "Assembly instruction missing.")

        cleared = session.set_source_breakpoints(source, [])
        self.assertEqual(len(cleared.body.breakpoints), 0, "Expects no breakpoints.")

        insts_no_bp = top_frame.disassemble()
        pc_no_bp = insts_no_bp[0]
        self.assertIsNotNone(pc_no_bp.location, "Source location missing.")
        self.assertEqual(pc_no_bp.line, bp_line, "Expects the same line number")
        self.assertTrue(pc_no_bp.instruction, "Assembly instruction missing.")

        # The disassembly instructions should be the same with breakpoint and
        # no breakpoint.
        self.assertEqual(
            insts_with_bp,
            insts_no_bp,
            "Expects instructions are the same after removing breakpoints.",
        )

        session.continue_to_exit()

    @skipIfWindows
    def test_disassemble_backwards(self):
        """`disassemble` with a negative `instructionOffset` returns the
        requested number of instructions, with the memoryReference at the
        expected index in the middle of the returned window."""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = self.getSourcePath("main.c")
        bp_line = line_number(source, "// breakpoint 1")
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [bp_line])
        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)

        caller_frame = session.thread_context_from(stop_event).frames(levels=2)[1]
        instruction_pointer_ref = self.expect_not_none(
            caller_frame.frame.instructionPointerReference
        )

        backwards_instructions = 200
        instructions_count = 400
        instructions = session.disassemble(
            memoryReference=instruction_pointer_ref,
            instructionOffset=-backwards_instructions,
            instructionCount=instructions_count,
        )

        self.assertEqual(
            len(instructions),
            instructions_count,
            "Disassemble request should return the exact requested number of instructions.",
        )

        frame_instruction_index = next(
            (
                i
                for i, inst in enumerate(instructions)
                if inst.address == instruction_pointer_ref
            ),
            -1,
        )
        self.assertEqual(
            frame_instruction_index,
            backwards_instructions,
            f"requested instruction should be preceded by {backwards_instructions} "
            f"instructions. Actual index: {frame_instruction_index}",
        )

        session.set_source_breakpoints(source, [])
        session.continue_to_exit()

    def test_disassemble_empty_memory_reference(self):
        """An empty `memoryReference` returns the requested count of invalid
        placeholder instructions instead of erroring out."""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = self.getSourcePath("main.c")
        bp_line = line_number(source, "// breakpoint 1")
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [bp_line])
        session.verify_stopped_on_breakpoint(after=ctx.process_event)

        instructions = session.disassemble(
            memoryReference="", instructionOffset=0, instructionCount=50
        )
        self.assertEqual(len(instructions), 50)
        for instruction in instructions:
            self.assertEqual(instruction.presentationHint, "invalid")

        session.set_source_breakpoints(source, [])
        session.continue_to_exit()
