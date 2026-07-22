"""
Test that we stop at runtime instrumentation locations (ubsan).
"""

import os
from lldbsuite.test.decorators import *
from lldbsuite.test.lldbtest import *
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_ubsan(DAPTestCaseBase):
    TEST_PROGRAM = r"""
int main(int argc, char const *argv[]) {
  int data[4] = {0};
  int *p = data + 5; // ubsan
  return *p;
}
"""
    IS_C = True

    def build(self, filename=None):
        file = self.create_file(self.TEST_PROGRAM, "main.c")
        bin_path = Path(self.lldbDAPExec).parent
        clang = os.path.join(bin_path, "clang")
        self.logger.info("clang: %s", clang)
        self.logger.info("file: %s", file)
        out_path = os.path.join(self.getBuildDir(), "a.out")
        commands = [clang, "-fsanitize=undefined", "-g", "-O0", file]

        # fmt: off
        if self.platformIsDarwin():
            clang_path = subprocess.check_output(["xcrun", "-find", "clang"]).decode().strip()
            lto_lib = (Path(clang_path).parent / "../lib/libLTO.dylib").resolve()

            sdk_path = subprocess.check_output(["xcrun", "--show-sdk-path"]).decode().strip()
            ASAN_LDFLAGS = ["-isysroot", sdk_path, "-Wl,-lto_library", f"-Wl,{lto_lib}"]
            commands.extend(ASAN_LDFLAGS)
        # fmt: on
        commands.extend(["-o", out_path])
        self.run_command(commands)

    @skipUnlessUndefinedBehaviorSanitizer
    def test_ubsan(self):
        """
        Test that we stop at ubsan.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program))
        stop_event = session.verify_stopped_on_exception(
            after=process_event, expected_description=r"Out of bounds index"
        )

        thread_id = self.expect_not_none(stop_event.body.threadId)
        exception_info = session.get_exception_info(thread_id)

        self.assertEqual(exception_info.breakMode, "always")
        description = self.expect_not_none(exception_info.description)
        self.assertRegex(description, r"Out of bounds index")
        self.assertEqual(exception_info.exceptionId, "runtime-instrumentation")

        # FIXME: Check on non macOS platform the stop information location heuristic
        # may be wrong. enable when we have updated Ubsan stopInfo heuristic.
        if self.platformIsDarwin():
            exception_details = self.expect_not_none(exception_info.details)
            stack_trace = self.expect_not_none(exception_details.stackTrace)
            self.assertIn("main.c", stack_trace)
