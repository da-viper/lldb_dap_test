"""
Test lldb-dap setFunctionBreakpoints request
"""

import sys

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.tools.lldb_dap.dap_types import (
    DAPTestGetTargetBreakpointsArgs,
    LaunchArgs,
)
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_setFunctionBreakpoints(DAPTestCaseBase):
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

    def build(self, filename=None):
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

        program_path = self.create_file(self.TEST_PROGRAM, "main.cpp")
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

    @skipIfWindows
    def test_set_and_clear(self):
        """Tests setting and clearing function breakpoints.
        This packet is a bit tricky on the debug adapter side since there
        is no "clearFunction Breakpoints" packet. Function breakpoints
        are set by sending a "setFunctionBreakpoints" packet with zero or
        more function names. If function breakpoints have been set before,
        any existing breakpoints must remain set, and any new breakpoints
        must be created, and any breakpoints that were in previous requests
        and are not in the current request must be removed. This function
        tests this setting and clearing and makes sure things happen
        correctly. It doesn't test hitting breakpoints and the functionality
        of each breakpoint, like 'conditions' and 'hitCondition' settings.
        """
        # Visual Studio Code Debug Adapters have no way to specify the file
        # without launching or attaching to a process, so we must start a
        # process in order to be able to set breakpoints.
        session = self.build_and_create_session()
        session.initialize_and_launch(LaunchArgs(self.getBuildArtifact("a.out")))

        functions = ["twelve"]
        # Set a function breakpoint at 'twelve'
        response = session.set_function_breakpoints(functions)
        breakpoints = response.body.breakpoints
        self.assertEqual(
            len(breakpoints),
            len(functions),
            f"expect {len(functions)} source breakpoints",
        )
        bp_id_12 = self.expect_not_none(breakpoints[0].id)
        self.assertTrue(breakpoints[0].verified, "expect breakpoint verified")

        # Add an extra name and make sure we have two breakpoints after this.
        functions.append("thirteen")
        response = session.set_function_breakpoints(functions)
        breakpoints = response.body.breakpoints
        self.assertEqual(
            len(breakpoints),
            len(functions),
            f"expect {len(functions)} source breakpoints",
        )
        for bp in breakpoints:
            self.assertTrue(bp.verified, "expect breakpoint verified")

        # There is no breakpoint delete packet, clients just send another
        # setFunctionBreakpoints packet with the different function names.
        functions.remove("thirteen")
        response = session.set_function_breakpoints(functions)
        breakpoints = response.body.breakpoints
        self.assertEqual(
            len(breakpoints),
            len(functions),
            f"expect {len(functions)} source breakpoints",
        )
        for bp in breakpoints:
            self.assertEqual(bp.id, bp_id_12, 'verify "twelve" breakpoint ID is same')
            self.assertTrue(bp.verified, "expect breakpoint still verified")

        # Now get the full list of breakpoints set in the target and verify
        # we have only 1 breakpoints set. The response above could have told
        # us about 1 breakpoints, but we want to make sure we don't have the
        # second one still set in the target
        response = session.send_request(DAPTestGetTargetBreakpointsArgs()).result()
        breakpoints = response.body.breakpoints
        self.assertEqual(
            len(breakpoints),
            len(functions),
            f"expect {len(functions)} source breakpoints",
        )
        for bp in breakpoints:
            self.assertEqual(bp.id, bp_id_12, 'verify "twelve" breakpoint ID is same')
            self.assertTrue(bp.verified, "expect breakpoint still verified")

        # Now clear all breakpoints for the source file by passing down an
        # empty lines array
        functions = []
        response = session.set_function_breakpoints(functions)
        breakpoints = response.body.breakpoints
        self.assertEqual(
            len(breakpoints),
            len(functions),
            f"expect {len(functions)} source breakpoints",
        )

        # Verify with the target that all breakpoints have been cleared
        response = session.send_request(DAPTestGetTargetBreakpointsArgs()).result()
        breakpoints = response.body.breakpoints
        self.assertEqual(
            len(breakpoints),
            len(functions),
            f"expect {len(functions)} source breakpoints",
        )

    @skipIfWindows
    def test_functionality(self):
        """Tests hitting breakpoints and the functionality of a single
        breakpoint, like 'conditions' and 'hitCondition' settings."""
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")

        # Set a breakpoint on "twelve" with no condition and no hitCondition.
        functions = ["twelve"]
        with session.configure(LaunchArgs(program)) as ctx:
            [bp_id] = session.resolve_function_breakpoints(functions)

        # Verify we hit the breakpoint we just set.
        stop_event = session.verify_stopped_on_breakpoint(
            bp_id, after=ctx.process_event
        )

        # Make sure i is zero at first breakpoint.
        thread_ctx = session.thread_context_from(stop_event)
        i = thread_ctx.top_frame().locals["i"].value_as_int
        self.assertEqual(i, 0, "i != 0 after hitting breakpoint")

        # Update the condition on our breakpoint.
        [new_bp_id] = session.resolve_function_breakpoints(functions, condition="i==4")
        self.assertEqual(
            bp_id,
            new_bp_id,
            "existing breakpoint should have its condition updated",
        )

        session.continue_to_breakpoint(bp_id)
        i = thread_ctx.top_frame().locals["i"].value_as_int
        self.assertEqual(i, 4, "i != 4 showing conditional works")

        response = session.set_function_breakpoints(functions, hitCondition="2")
        new_bp_id = self.expect_not_none(response.body.breakpoints[0].id)
        self.assertEqual(
            bp_id,
            new_bp_id,
            "existing breakpoint should have its condition updated",
        )

        # Continue with a hitCondition of 2 and expect it to skip 1 value.
        session.continue_to_breakpoint(bp_id)
        i = thread_ctx.top_frame().locals["i"].value_as_int
        self.assertEqual(i, 6, "i != 6 showing hitCondition works")

        # Continue after hitting our hitCondition and make sure it only goes
        # up by 1.
        session.continue_to_breakpoint(bp_id)
        i = thread_ctx.top_frame().locals["i"].value_as_int
        self.assertEqual(i, 7, "i != 7 showing post hitCondition hits every time")
