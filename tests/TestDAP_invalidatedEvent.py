"""
Test lldb-dap recieves invalidated-events when the area such as
stack, variables, threads has changes but the client does not
know about it.
"""

# import lldbdap_testcase
# from lldbsuite.test.lldbtest import line_number
# from dap_server import Event


from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number
from lldb_dap.dap_types import LaunchArgs, StackTraceArgs

OTHER_H = r"""
#ifndef OTHER_H
#define OTHER_H

int add(int a, int b) {
  int first = a;
  int second = b; // thread return breakpoint
  int result = first + second;
  return result;
}
#endif // OTHER_H
"""


class TestDAP_invalidatedEvent(DAPTestCaseBase):
    TEST_PROGRAM = r"""#include "other.h"

int main() {
  int first = 5;
  int second = 10;
  const int result = add(first, second);

  return 0;
}
"""

    def verify_top_frame_name(self, frame_name: str, thread_id: int):
        response = self.session.request_and_respond(StackTraceArgs(thread_id))
        all_frames = response.body.stackFrames

        self.assertGreaterEqual(len(all_frames), 1, "Expected at least one frame.")
        top_frame_name = all_frames[0].name
        self.assertRegex(top_frame_name, f"{frame_name}.*")
        return response

    def test_invalidated_stack_area_event(self):
        """
        Test an invalidated event for the stack area.
        The event is sent when the command `thread return <expr>` is sent by the user.
        """
        other_source = self.create_file(OTHER_H, "other.h")
        return_bp_line = line_number(other_source, "// thread return breakpoint")

        program = self.create_test_program_with_name("main.cpp")
        session = self.session
        launch_args = LaunchArgs(program=program)
        with session.configure(launch_args) as ctx:
            session.resolve_source_breakpoints(other_source, [return_bp_line])
        process_event = ctx.process_event()
        stopped_event = session.verify_stopped_on_breakpoint(after=process_event)

        thread_id = self.expect_is_not_none(
            stopped_event.body.threadId, "expected a thread id."
        )
        stack_response = self.verify_top_frame_name("add", thread_id)

        # run thread return
        thread_command = "thread return 20"
        self.session.evaluate(thread_command, context="repl")

        # wait for the invalidated stack event.
        invalid_event = self.session.wait_for_invalidated(after=stack_response)
        self.assertIsNotNone(invalid_event, "Expected an invalidated event.")
        event_body = invalid_event.body
        self.assertIsNotNone(event_body.areas)
        self.assertIn("stacks", event_body.areas or [])
        self.assertIsNotNone(event_body.threadId)
        self.assertEqual(
            thread_id,
            event_body.threadId,
            f"Expected the event from thread {thread_id}.",
        )

        # confirm we are back at the main frame.
        thread_id = self.expect_is_not_none(
            invalid_event.body.threadId, "expected a thread id."
        )
        self.verify_top_frame_name("main", thread_id)
        session.continue_to_exit()
