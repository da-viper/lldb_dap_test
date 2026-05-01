"""
Test lldb-dap disassemble request
"""


import unittest

from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number
from lldb_dap.dap_types import LaunchArgs


@unittest.skip("NOT FULLY IMPLEMENTED")
class TestDAP_disassemble(DAPTestCaseBase):
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

    # @skipIfWindows TODO: Fix
    def test_disassemble(self):
        """Tests the 'disassemble' request."""
        program = self.create_test_program_with_name("main.c")
        session = self.session
        source = "main.c"
        bp_line_no = line_number(source, "// breakpoint 1")
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [bp_line_no])
        process_event = ctx.process_event()
        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        insts_with_bp, pc_with_bp_assembly = self.disassemble(frameIndex=0)
        self.assertIn("location", pc_with_bp_assembly, "Source location missing.")
        self.assertEqual(
            pc_with_bp_assembly["line"], bp_line_no, "Expects the same line number"
        )
        no_bp = self.set_source_breakpoints(source, [])
        self.assertEqual(len(no_bp), 0, "Expects no breakpoints.")
        self.assertIn(
            "instruction", pc_with_bp_assembly, "Assembly instruction missing."
        )

        insts_no_bp, pc_no_bp_assembly = self.disassemble(frameIndex=0)
        self.assertIn("location", pc_no_bp_assembly, "Source location missing.")
        self.assertEqual(
            pc_with_bp_assembly["line"], bp_line_no, "Expects the same line number"
        )
        # the disassembly instructions should be the same with breakpoint and no breakpoint;
        self.assertDictEqual(
            insts_with_bp,
            insts_no_bp,
            "Expects instructions are the same after removing breakpoints.",
        )
        self.assertIn("instruction", pc_no_bp_assembly, "Assembly instruction missing.")

        self.continue_to_exit()

    # @skipIfWindows TODO:
    def test_disassemble_backwards(self):
        """
        Tests the 'disassemble' request with a backwards disassembly range.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(program)
        source = "main.c"
        self.set_source_breakpoints(source, [line_number(source, "// breakpoint 1")])
        self.continue_to_next_stop()

        instruction_pointer_reference = self.get_stackFrames()[1][
            "instructionPointerReference"
        ]
        backwards_instructions = 200
        instructions_count = 400
        instructions = self.dap_server.request_disassemble(
            memoryReference=instruction_pointer_reference,
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
                for i, instruction in enumerate(instructions)
                if instruction["address"] == instruction_pointer_reference
            ),
            -1,
        )
        self.assertEqual(
            frame_instruction_index,
            backwards_instructions,
            f"requested instruction should be preceeded by {backwards_instructions} instructions. Actual index: {frame_instruction_index}",
        )

        # clear breakpoints
        self.set_source_breakpoints(source, [])
        self.continue_to_exit()

    def test_disassemble_empty_memory_reference(self):
        """
        Tests the 'disassemble' request with empty memory reference.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(program)
        source = "main.c"
        bp_line_no = line_number(source, "// breakpoint 1")
        self.set_source_breakpoints(source, [bp_line_no])
        self.continue_to_next_stop()

        instructions = self.dap_server.request_disassemble(
            memoryReference="", instructionOffset=0, instructionCount=50
        )
        self.assertEqual(len(instructions), 50)
        for instruction in instructions:
            self.assertEqual(instruction["presentationHint"], "invalid")

        # clear breakpoints
        self.set_source_breakpoints(source, [])
        self.continue_to_exit()
