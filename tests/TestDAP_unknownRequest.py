"""
Test lldb-dap unknown request.
"""

from typing import Optional
from lldb_dap.dap_types import EmptyBodyResponse
from dataclasses import dataclass
from lldb_dap.dap_types import LaunchArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase


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

    def test_no_arguments(self):
        program = self.create_test_program_with_name("main.c")
        session = self.session
        process_event, _ = session.launch_using_config(
            LaunchArgs(program, stopOnEntry=True)
        )
        session.verify_stopped_on_entry(after=process_event)

        handle = session.send_request(UnknownArgs())
        response = session.get_error_response(handle)
        self.assertFalse(response.success)
        self.assertEqual(response.body.error.format, "unknown request")

        session.continue_to_exit()

    def test_with_arguments(self):
        program = self.create_test_program_with_name("main.c")
        session = self.session
        process_event, _ = session.launch_using_config(
            LaunchArgs(program, stopOnEntry=True)
        )
        session.verify_stopped_on_entry(after=process_event)

        handle = session.send_request(UnknownArgs(foo="bar", id=42))
        response = session.get_error_response(handle)
        self.assertFalse(response.success)
        self.assertEqual(response.body.error.format, "unknown request")

        session.continue_to_exit()
