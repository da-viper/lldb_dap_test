"""
Test lldb-dap send-event integration.
"""


import json
from dataclasses import asdict, dataclass
from typing import List, Optional

from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.dap_types import Event, LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


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
    IS_C = True

    def test_send_event(self):
        """
        Test sending a custom event.
        """
        session = self.build_and_create_session()
        source = "main.c"
        program = self.getBuildArtifact("a.out")
        custom_event_body = CustomEvent.Body(key=321, arr=[True])

        launch_args = LaunchArgs(
            program,
            stopCommands=[
                "lldb-dap send-event my-custom-event ",
                "lldb-dap send-event my-custom-event '{}'".format(
                    json.dumps(asdict(custom_event_body))
                ),
            ],
        )
        with session.configure(launch_args) as ctx:
            breakpoint_line = line_number(source, "// breakpoint")
            session.resolve_source_breakpoints(source, [breakpoint_line])
        process_event = ctx.process_event

        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        custom_event = session.wait_for_event(CustomEvent, after=stop_event)
        self.assertEqual(custom_event.event, "my-custom-event")
        self.assertIsNone(custom_event.body, None)

        custom_event_with_body = session.wait_for_event(CustomEvent, after=custom_event)
        self.assertEqual(custom_event_with_body.event, "my-custom-event")
        self.assertEqual(custom_event_with_body.body, custom_event_body)

    def test_send_internal_event(self):
        """
        Test sending an internal event produces an error.
        """
        source = "main.c"
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program, stopOnEntry=True))

        session.verify_stopped_on_entry(after=process_event)
        result = session.do_evaluate("`lldb-dap send-event stopped").result().body.result

        self.assertRegex(
            result,
            r"Invalid use of lldb-dap send-event, event \"stopped\" should be handled by lldb-dap internally.",
        )
