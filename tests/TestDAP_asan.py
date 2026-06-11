"""
Test that we stop at runtime instrumentation locations (asan).
"""

from lldbsuite.test.decorators import *
from lldbsuite.test.lldbtest import *
from lldbsuite.test.tools.lldb_dap import lldb_dap_testcase
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs


class TestDAP_asan(lldb_dap_testcase.DAPTestCaseBase):
    TEST_PROGRAM = r"""int main() {
  int *array = new int[100];
  delete[] array;
  return array[42]; // asan
}

"""

    def build(self, filename=None):
        file = self.create_file(self.TEST_PROGRAM, "main.cpp")
        bin_path = Path(self.lldbDAPExec).parent
        clang = os.path.join(bin_path, "clang++")
        self.logger.info("clang: %s", clang)
        self.logger.info("file: %s", file)
        out_path = os.path.join(self.getBuildDir(), "a.out")
        commands = [clang, "-fsanitize=address", "-g", "-O0", file]

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

    @skipUnlessAddressSanitizer
    def test_asan(self):
        """
        Test that we stop at asan.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program))
        stop_event = session.verify_stopped_on_exception(
            after=process_event, expected_description="Use of deallocated memory"
        )

        thread_id = self.expect_not_none(stop_event.body.threadId)
        exception_info = session.get_exception_info(thread_id)
        self.assertEqual(exception_info.breakMode, "always")
        description = self.expect_not_none(exception_info.description)
        self.assertRegex(description, r"fatal_error: heap-use-after-free")
        self.assertEqual(exception_info.exceptionId, "runtime-instrumentation")
