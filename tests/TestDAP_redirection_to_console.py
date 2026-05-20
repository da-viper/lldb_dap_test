from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.lldbtest import line_number


class TestDAP_redirection_to_console(DAPTestCaseBase):
    TEST_PROGRAM = r"""
int multiply(int x, int y) {
  return x * y; // breakpoint 1
}

int main(int argc, char const *argv[]) {
  int result = multiply(argc, 20);
  return result < 0;
}

"""
    LLDB_DAP_ENV = {"LLDB_DAP_TEST_STDOUT_STDERR_REDIRECTION": ""}

    def build(self):
        self.create_test_program_with_name("main.cpp")

    def test(self):
        """
        # TODO: THIS IS NOT THE CASE ANY MORE !!! recheck this.
        Without proper stderr and stdout redirection, the following code would throw an
        exception, like the following:

            Exception: unexpected malformed message from lldb-dap
        """
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        source = "main.cpp"
        breakpoint1_line = line_number(source, "// breakpoint 1")
        with session.configure(LaunchArgs(program)) as ctx:
            breakpoint_ids = session.resolve_source_breakpoints(
                source, [breakpoint1_line]
            )
        process_event = ctx.process_event()
        stop_event = session.verify_stopped_on_breakpoint(
            breakpoint_ids, after=process_event
        )

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        local_variables = thread_ctx.frames()[1].locals
        local_names = [var.name for var in local_variables]
        self.assertIn("argc", local_names)
