"""
Test lldb-dap breakpointLocations request
"""


import sys
from typing import List, Tuple

import os

from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number
from lldb_dap.dap_types import BreakpointLocation, LaunchArgs


class TestDAP_breakpointLocations(DAPTestCaseBase):
    TEST_PROGRAM = r"""#include <dlfcn.h>
#include <stdexcept>
#include <stdio.h>

int twelve(int i) {
  return 12 + i; // break 12
}

int thirteen(int i) {
  return 13 + i; // break 13
}

namespace a {
int fourteen(int i) {
  return 14 + i; // break 14
}
} // namespace a
int main(int argc, char const *argv[]) {
#if defined(__APPLE__)
  const char *libother_name = "libother.dylib";
#else
  const char *libother_name = "libother.so";
#endif

  void *handle = dlopen(libother_name, RTLD_NOW);
  if (handle == nullptr) {
    fprintf(stderr, "%s\n", dlerror());
    exit(1);
  }

  const char *message = "Hello from main!";
  int (*foo)(int) = (int (*)(int))dlsym(handle, "foo");
  if (foo == nullptr) {
    fprintf(stderr, "%s\n", dlerror());
    exit(2);
  } // break non-breakpointable line
  foo(12); // before loop

  for (int i = 0; i < 10; ++i) {
    int x = twelve(i) + thirteen(i) + a::fourteen(i); // break loop
  }
  printf("%s\n", message);
  try {
    throw std::invalid_argument("throwing exception for testing");
  } catch (...) {
    puts("caught exception...");
  }
  return 0; // after loop
}

"""
    OTHER_C = r"""extern int foo(int x) {
  int y = x + 42; // break other
  int z = y + 42;
  return z;
}
"""

    def build(self):
        main_basename = "main-copy.cpp"
        # TODO: START -- this is not needed when we port
        other = self.create_file(self.OTHER_C, "other.c")
        shared_lib_name = "libother.so" if sys.platform == "linux" else "libother.dylib"
        self.run_command(
            [
                "/usr/bin/clang",
                "-fPIC",
                "-g",
                "-shared",
                other,
                "-o",
                self.getBuildArtifact(shared_lib_name),
            ]
        )

        program_path = self.create_file(self.TEST_PROGRAM, main_basename)
        self.run_command(
            [
                "/usr/bin/clang++",
                "-fPIC",
                "-g",
                program_path,
                f"-Wl,-rpath,{self.test_dir}",
                "-ldl",
                "-o",
                self.getBuildArtifact("a.out"),
            ]
        )
        # TODO: END ---

    # @skipIfWindows TODO:
    def test_column_breakpoints(self):
        self.build()
        main_path = os.path.realpath(self.getSourcePath("main-copy.cpp"))
        """Test retrieving the available breakpoint locations."""
        program = self.getBuildArtifact("a.out")
        session = self.session
        process_event, _ = session.launch_using_config(
            LaunchArgs(program, stopOnEntry=True)
        )
        session.verify_stopped_on_entry(after=process_event)

        # Ask for the breakpoint locations based only on the line number
        loop_line = line_number(main_path, "// break loop")
        response = session.set_breakpoint_locations(main_path, loop_line)
        self.assertTrue(response.success)
        breakpoint_locations = response.body.breakpoints

        expected_columns = [9, 13, 20, 23, 25, 34, 37, 39, 51]
        expected_locations = [
            BreakpointLocation(line=loop_line, column=column)
            for column in expected_columns
        ]
        self.assertEqual(breakpoint_locations, expected_locations)

        # Ask for the breakpoint locations for a column range
        response = session.set_breakpoint_locations(
            main_path, loop_line, column=24, endColumn=46
        )
        self.assertTrue(response.success)
        breakpoint_locations = response.body.breakpoints
        expected_columns = [25, 34, 37, 39]
        expected_locations = [
            BreakpointLocation(line=loop_line, column=column)
            for column in expected_columns
        ]
        self.assertEqual(breakpoint_locations, expected_locations)

        # Ask for the breakpoint locations for a range of line numbers
        response = session.set_breakpoint_locations(
            main_path, line=loop_line, column=39, endLine=loop_line + 2
        )
        self.maxDiff = None
        self.assertTrue(response.success)
        # On some systems, there is an additional breakpoint available
        # at line 41, column 3, i.e. at the end of the loop. To make this
        # test more portable, only check that all expected breakpoints are
        # presented, but also accept additional breakpoints.
        expected_line_columns: List[Tuple[int, int]] = [
            # (line, column)
            (40, 39),
            (40, 51),
            (42, 3),
            (42, 18),
        ]
        expected_locations = [
            BreakpointLocation(line=line, column=column)
            for line, column in expected_line_columns
        ]
        breakpoint_locations = response.body.breakpoints
        for bp in expected_locations:
            self.assertIn(bp, breakpoint_locations)

        session.continue_to_exit()
