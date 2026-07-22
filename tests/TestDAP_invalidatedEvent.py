"""
Test lldb-dap recieves invalidated-events when the area such as
stack, variables, threads has changes but the client does not
know about it.
"""

from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs, StackTraceArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase
from lldbsuite.test.tools.lldb_dap.session_helpers import DAPTestSession

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

    def build(self, filename=None):
        other_source = self.create_file(OTHER_H, "other.h")
        super().build()

    def verify_top_frame_name(
        self, session: DAPTestSession, frame_name: str, thread_id: int
    ):
        response = session.stack_trace(thread_id)
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
        other_source = self.getSourcePath("other.h")
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        with session.configure(LaunchArgs(program)) as ctx:
            return_bp_line = line_number(other_source, "// thread return breakpoint")
            session.resolve_source_breakpoints(other_source, [return_bp_line])

        stopped_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)

        thread_ctx = session.thread_context_from(stopped_event)
        top_frame = thread_ctx.top_frame()
        self.assertRegex(top_frame.name, "add.*")

        last_event = session.last_event()
        # Run thread return.
        session.evaluate("thread return 20", context="repl")

        # Wait for the invalidated stack event.
        invalid_event = session.wait_for_invalidated_event(after=last_event)
        self.assertIsNotNone(invalid_event, "Expected an invalidated event.")
        event_body = invalid_event.body
        self.assertIsNotNone(event_body.areas)
        self.assertIn("stacks", event_body.areas or [])
        self.assertIsNotNone(event_body.threadId)
        self.assertEqual(
            thread_ctx.thread_id,
            event_body.threadId,
            f"Expected the event from thread {thread_ctx.thread_id}.",
        )

        # Confirm we are back at the main frame.
        top_frame = session.top_frame_from(invalid_event)
        self.assertRegex(top_frame.name, "main.*")
        session.continue_to_exit()
