"""
Test exception behavior in DAP with c++ throw.
"""


from typing import cast
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import ExceptionBreakMode, LaunchArgs
from lldbsuite.test.decorators import skipIfWindows


class TestDAP_exception_cpp(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <stdexcept>

int main(int argc, char const *argv[]) {
  throw std::invalid_argument("throwing exception for testing");
  return 0;
}
"""

    @skipIfWindows
    def test_stopped_description(self):
        """
        Test that exception description is shown correctly in stopped
        event.
        """

        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch_using_config(LaunchArgs(program=program))

        stopped_event = session.verify_stopped_on_exception(
            after=process_event, expected_description="signal SIGABRT"
        )

        thread_id = self.expect_is_not_none(stopped_event.body.threadId)
        exception_info = session.get_exception_info(thread_id)

        self.assertEqual(exception_info.breakMode, ExceptionBreakMode.ALWAYS)
        description = self.expect_is_not_none(exception_info.description)
        self.assertIn("signal SIGABRT", description)
        self.assertEqual(exception_info.exceptionId, "signal")
        self.assertIsNotNone(exception_info.details)
