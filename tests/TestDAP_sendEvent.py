"""
Test lldb-dap send-event integration.
"""


import json
from dataclasses import asdict, dataclass
from typing import List, Optional

from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number
from lldb_dap.dap_types import Event, LaunchArgs


@dataclass(frozen=True)
class CustomEvent(Event, event="my-custom-event"):
    @dataclass
    class Body:
        key: int
        arr: List[bool]

    body: Optional[Body] = None


class TestDAP_sendEvent(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <stdio.h>

int main(int argc, char const *argv[]) {
  printf("example\n"); // breakpoint 1
  return 0;
}
"""

    def test_send_event(self):
        """
        Test sending a custom event.
        """
        source = "main.c"
        program = self.create_test_program_with_name(source)
        custom_event_body = CustomEvent.Body(key=321, arr=[True])

        breakpoint_line = line_number(source, "// breakpoint")
        launch_args = LaunchArgs(
            program,
            stopCommands=[
                "lldb-dap send-event my-custom-event ",
                "lldb-dap send-event my-custom-event '{}'".format(
                    json.dumps(asdict(custom_event_body))
                ),
            ],
        )
        with self.session.configure(launch_args) as ctx:
            self.session.resolve_source_breakpoints(source, [breakpoint_line])
        process_event = ctx.process_event()

        stop_event = self.session.verify_stopped_on_breakpoint(after=process_event)

        custom_event = self.session.wait_for_event(CustomEvent, after=stop_event)
        self.assertEqual(custom_event.event, "my-custom-event")
        self.assertIsNone(custom_event.body, None)

        custom_event_with_body = self.session.wait_for_event(
            CustomEvent, after=custom_event
        )
        self.assertEqual(custom_event_with_body.event, "my-custom-event")
        self.assertEqual(custom_event_with_body.body, custom_event_body)

    def test_send_internal_event(self):
        """
        Test sending an internal event produces an error.
        """
        source = "main.c"
        program = self.create_test_program_with_name(source)
        process_event, _ = self.session.launch_using_config(
            LaunchArgs(program, stopOnEntry=True)
        )

        self.session.verify_stopped_on_entry(after=process_event)
        result = self.session.evaluate("`lldb-dap send-event stopped").result

        self.assertRegex(
            result,
            r"Invalid use of lldb-dap send-event, event \"stopped\" should be handled by lldb-dap internally.",
        )
