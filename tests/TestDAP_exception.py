"""
Test exception behavior in DAP with signal.
"""

from lldbsuite.test.decorators import skipIfNoSignals
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


@skipIfNoSignals
class TestDAP_exception(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <signal.h>

int main(int argc, char const *argv[]) {
  raise(SIGABRT);
  return 0;
}

"""
    IS_C = True

    def test_stopped_description(self):
        """
        Test that exception description is shown correctly in stopped
        event.
        """

        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program=program))

        stopped_event = session.verify_stopped_on_exception(
            expected_description="signal SIGABRT", after=process_event
        )
        thread_id = self.expect_not_none(stopped_event.body.threadId)
        exception_info = session.get_exception_info(thread_id)

        self.assertEqual(exception_info.breakMode, "always")
        description = self.expect_not_none(exception_info.description)
        self.assertEqual(description, "signal SIGABRT")
        self.assertEqual(exception_info.exceptionId, "signal")
