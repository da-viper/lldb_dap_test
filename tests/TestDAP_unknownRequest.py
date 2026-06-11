"""
Test lldb-dap unknown request.
"""

from dataclasses import dataclass
from typing import Optional

from lldbsuite.test.tools.lldb_dap.dap_types import EmptyBodyResponse, LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


@dataclass(frozen=True)
class UnknownArgs:
    foo: Optional[str] = None
    id: Optional[int] = None

    command_ = "unknown"
    response_class_ = EmptyBodyResponse


class TestDAP_unknown_request(DAPTestCaseBase):
    """
    Tests handling of unknown request.
    """

    TEST_PROGRAM = r"""
#include <stdio.h>

int main() {
  printf("Hello, World!\n");
  return 0;
}
"""
    IS_C = True

    def test_no_arguments(self):
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        process_event = session.launch(LaunchArgs(program, stopOnEntry=True))
        session.verify_stopped_on_entry(after=process_event)

        handle = session.send_request(UnknownArgs())
        response = handle.error()
        self.assertFalse(response.success)
        self.assertEqual(response.body.error.format, "unknown request")

        session.continue_to_exit()

    def test_with_arguments(self):
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        process_event = session.launch(LaunchArgs(program, stopOnEntry=True))
        session.verify_stopped_on_entry(after=process_event)

        handle = session.send_request(UnknownArgs(foo="bar", id=42))
        response = handle.error()
        self.assertFalse(response.success)
        self.assertEqual(response.body.error.format, "unknown request")

        session.continue_to_exit()
