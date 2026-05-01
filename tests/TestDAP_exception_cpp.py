"""
Test exception behavior in DAP with c++ throw.
"""


from typing import cast
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import ExceptionBreakMode, LaunchArgs


class TestDAP_exception_cpp(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <stdexcept>

int main(int argc, char const *argv[]) {
  throw std::invalid_argument("throwing exception for testing");
  return 0;
}
"""

    # @skipIfWindows
    def test_stopped_description(self):
        """
        Test that exception description is shown correctly in stopped
        event.
        """

        program = self.create_test_program_with_name("main.cpp")
        process_event, _ = self.session.launch_using_config(LaunchArgs(program=program))

        stopped_event = self.session.verify_stopped_on_exception(
            after=process_event, expected_description="signal SIGABRT"
        )

        thread_id = self.expect_is_not_none(stopped_event.body.threadId)
        exception_info = self.session.get_exception_info(thread_id)

        self.assertEqual(exception_info.breakMode, ExceptionBreakMode.ALWAYS)
        self.assertIsNotNone(exception_info.description)
        self.assertIn("signal SIGABRT", exception_info.description)
        self.assertEqual(exception_info.exceptionId, "signal")
        self.assertIsNotNone(exception_info.details)
