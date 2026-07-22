"""
Test lldb-dap setExceptionBreakpoints request
"""

import sys

from lldbsuite.test.decorators import (
    skipIfTargetDoesNotSupportSharedLibraries,
    skipIfWindows,
)
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


@skipIfTargetDoesNotSupportSharedLibraries()
class TestDAP_setExceptionBreakpoints(DAPTestCaseBase):
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
    def test_functionality(self):
        """Tests setting and clearing exception breakpoints.
        This packet is a bit tricky on the debug adapter side since there
        is no "clear exception breakpoints" packet. Exception breakpoints
        are set by sending a "setExceptionBreakpoints" packet with zero or
        more exception filters. If exception breakpoints have been set
        before, any existing breakpoints must remain set, and any new
        breakpoints must be created, and any breakpoints that were in
        previous requests and are not in the current request must be
        removed. This exception tests this setting and clearing and makes
        sure things happen correctly. It doesn't test hitting breakpoints
        and the functionality of each breakpoint, like 'conditions' and
        x'hitCondition' settings.
        """
        # Visual Studio Code Debug Adapters have no way to specify the file
        # without launching or attaching to a process, so we must start a
        # process in order to be able to set breakpoints.
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()

        with session.configure(LaunchArgs(program)) as ctx:
            response = session.set_exception_breakpoints(
                filters=["cpp_throw", "cpp_catch"]
            )
            breakpoints = self.expect_not_none(response.body.breakpoints)
            for bp in breakpoints:
                self.assertTrue(bp.verified, True)

        session.verify_stopped_on_exception(
            expected_description=r"breakpoint 1\.1",
            expected_text=r"C\+\+ Throw",
            after=ctx.process_event,
        )
        session.continue_to_exception_breakpoint(
            expected_description=r"breakpoint 2\.1", expected_text=r"C\+\+ Catch"
        )
        session.continue_to_exit()
