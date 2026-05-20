from lldb_dap.dap_types import StoppedReason
import sys
import unittest


from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.lldbtest import line_number

OTHER_C = r"""
extern int foo(int x) {
  int y = x + 42; // break other
  int z = y + 42;
  return z;
}
"""


class TestDAP_module_event(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char const *argv[]) {

#if defined(__APPLE__)
  const char *libother_name = "libother.dylib";
#else
  const char *libother_name = "libother.so";
#endif

  printf("before dlopen\n"); // breakpoint 1
  void *handle = dlopen(libother_name, RTLD_NOW);
  int (*foo)(int) = (int (*)(int))dlsym(handle, "foo");
  foo(12);

  printf("before dlclose\n"); // breakpoint 2
  dlclose(handle);
  printf("after dlclose\n"); // breakpoint 3

  return 0; // breakpoint 1
}
"""

    def test_module_event(self):
        # TODO: move this to build
        other = self.create_file(OTHER_C, "other.c")
        shared_lib_name = "libother.so" if sys.platform == "linux" else "libother.dylib"
        program_path = self.create_file(self.TEST_PROGRAM, "main.cpp")
        program = self.getBuildArtifact("a.out")
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
        self.run_command(
            [
                "/usr/bin/clang++",
                "-fPIC",
                "-g",
                program_path,
                f"-Wl,-rpath,{self.test_dir}",
                "-ldl",
                "-o",
                program,
            ]
        )
        session = self.create_session()

        source = "main.cpp"
        breakpoint1_line = line_number(source, "// breakpoint 1")
        breakpoint2_line = line_number(source, "// breakpoint 2")
        breakpoint3_line = line_number(source, "// breakpoint 3")

        with session.configure(LaunchArgs(program=program)) as ctx:
            session.resolve_source_breakpoints(
                source, [breakpoint1_line, breakpoint2_line, breakpoint3_line]
            )
        process_event = ctx.process_event()
        # Wait for the breakpoint before dlopen
        before_dlopen_event = session.verify_stopped_on_breakpoint(after=process_event)

        # Continue to the second breakpoint, before the dlclose.
        session.continue_to_next_stop(exp_reason=StoppedReason.BREAKPOINT)

        # Make sure we got a module event for libother.
        new_module_event = session.verify_next_module_event(after=before_dlopen_event)
        module_id = new_module_event.body.module.id
        self.assertEqual(new_module_event.body.reason, "new")
        self.assertIn("libother", new_module_event.body.module.name)

        # Continue to the third breakpoint, after the dlclose.
        session.continue_to_next_stop(exp_reason=StoppedReason.BREAKPOINT)

        # Make sure we got a module event for libother.
        removed_module_event = session.verify_next_module_event(after=new_module_event)
        reason = removed_module_event.body.reason
        self.assertEqual(reason, "removed")
        self.assertEqual(removed_module_event.body.module.id, module_id)

        # The removed module event should omit everything but the module id and name
        # as they are required fields.
        removed_module = removed_module_event.body.module
        self.assertIsNotNone(removed_module.id)
        self.assertIsNotNone(removed_module.name)
        self.assertEqual(removed_module.name, "", "expects empty name.")

        session.continue_to_exit()
