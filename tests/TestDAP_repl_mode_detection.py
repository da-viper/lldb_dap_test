"""
Test lldb-dap repl mode detection
"""

from typing import Optional

from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import (
    LaunchArgs,
    StackTraceArgs,
    StoppedEvent,
)
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_repl_mode_detection(DAPTestCaseBase):
    TEST_PROGRAM = r"""
void noop() {}

void fun() {
  int user_command = 474747;
  int alias_command = 474747;
  int alias_command_with_arg = 474747;
  int platform = 474747; // built-in command
  noop();                // breakpoint 1
}

int main() {
  fun();
  noop(); // breakpoint 2
  return 0;
}

"""

    def setUp(self):
        super().setUp()
        self._session = self.build_and_create_session()

    def get_frame_id_from_event(self, stopped_event: StoppedEvent):
        thread_id = self.expect_not_none(stopped_event.body.threadId)

        response = self._session.send_request(StackTraceArgs(thread_id)).result()
        all_frames = response.body.stackFrames

        self.assertGreaterEqual(len(all_frames), 1, "Expected at least one frame.")
        return all_frames[0].id

    def assertEvaluate(
        self, expression: str, regex: str, frame_id: Optional[int] = None
    ):
        result = self._session.evaluate(
            expression, context="repl", frameId=frame_id
        ).result
        self.assertRegex(result, regex)

    def test_completions(self):
        program = self.getBuildArtifact("a.out")
        session = self._session
        with session.configure(LaunchArgs(program)) as ctx:
            source = "main.cpp"
            breakpoint1_line = line_number(source, "// breakpoint 1")
            breakpoint2_line = line_number(source, "// breakpoint 2")

            session.resolve_source_breakpoints(
                source, [breakpoint1_line, breakpoint2_line]
            )

            self.assertEvaluate("lldb-dap repl-mode", "auto")
            # The result of the commands should return the empty string.
            self.assertEvaluate("`command regex user_command s/^$/platform/", r"^$")
            self.assertEvaluate("`command alias alias_command platform", r"^$")
            self.assertEvaluate(
                "`command alias alias_command_with_arg platform select --sysroot %1 remote-linux",
                r"^$",
            )

        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)
        top_frame = self.get_frame_id_from_event(stop_event)

        self.assertEvaluate("user_command", "474747", top_frame)
        self.assertEvaluate("alias_command", "474747", top_frame)
        self.assertEvaluate("alias_command_with_arg", "474747", top_frame)
        self.assertEvaluate("platform", "474747", top_frame)

        stop_event = session.continue_to_next_stop()
        top_frame = self.get_frame_id_from_event(stop_event)
        platform_help_needle = "Commands to manage and create platforms"
        self.assertEvaluate("user_command", platform_help_needle, top_frame)
        self.assertEvaluate("alias_command", platform_help_needle, top_frame)
        self.assertEvaluate(
            "alias_command_with_arg " + self.getBuildDir(),
            "Platform: remote-linux",
            top_frame,
        )
        self.assertEvaluate("platform", platform_help_needle, top_frame)
