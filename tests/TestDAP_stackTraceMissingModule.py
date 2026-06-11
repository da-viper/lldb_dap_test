"""
Test lldb-dap stack trace when module is missing
"""

import re

from lldbsuite.test.decorators import skipUnlessPlatform
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs, StoppedReason
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_stackTraceMissingModule(DAPTestCaseBase):
    TEST_PROGRAM = r"""#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

extern uint8_t __start_target_section[];
extern uint8_t __stop_target_section[];

__attribute__((used, section("target_section"))) int target_function(void) {
  return 42;
}

typedef int (*target_function_t)(void);

int main(void) {
  size_t target_function_size = __stop_target_section - __start_target_section;
  size_t page_size = sysconf(_SC_PAGESIZE);
  size_t page_aligned_size =
      (target_function_size + page_size - 1) & ~(page_size - 1);

  void *executable_memory =
      mmap(NULL, page_aligned_size, PROT_READ | PROT_WRITE | PROT_EXEC,
           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  if (executable_memory == MAP_FAILED) {
    perror("mmap");
    return 1;
  }

  memcpy(executable_memory, __start_target_section, target_function_size);

  target_function_t func = (target_function_t)executable_memory;
  int result = func(); // Break here
  printf("Result from target function: %d\n", result);

  return 0;
}

"""
    IS_C = True

    @skipUnlessPlatform(["linux"])
    def test_missingModule(self):
        """Test that the stack frame without a module still has assembly source."""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()

        with session.configure(LaunchArgs(program, commandEscapePrefix="")) as ctx:
            source = "main.c"
            session.set_source_breakpoints(
                source, [line_number(source, "// Break here")]
            )
        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)

        # Evaluate expr -- func
        expr_result = session.evaluate("expr -f pointer -- func", context="repl")
        expr_result_address = re.search(r"0x[0-9a-fA-F]+", expr_result.result)

        expr_address = self.expect_not_none(
            expr_result_address, "Failed to get address of dynamic allocated func"
        )
        func_address = expr_address.group(0)

        session.evaluate(f"breakpoint set --address {func_address}", context="repl")
        session.continue_to_next_stop(exp_reason=StoppedReason.BREAKPOINT)

        frame_without_module = session.top_frame_from(stop_event).frame

        self.assertIsNotNone(frame_without_module.line, "Line number missing.")
        self.assertIsNotNone(frame_without_module.column, "Column number missing.")
        frame_source = self.expect_not_none(
            frame_without_module.source, "Source location missing."
        )
        self.assertIsNotNone(frame_source.sourceReference, "Source reference missing.")
