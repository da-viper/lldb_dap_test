"""
Test lldb-dap stackTrace request with an extended backtrace thread.
"""

import os

from lldbsuite.test.decorators import skipUnlessDarwin
from lldbsuite.test.lldbplatformutil import findBacktraceRecordingDylib
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs, StackFrameFormat
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_extendedStackTrace(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#import <dispatch/dispatch.h>
#include <stdio.h>

void one() {
  printf("one...\n"); // breakpoint 1
}

void two() {
  printf("two...\n");
  one();
}

void three() {
  printf("three...\n");
  two();
}

int main(int argc, char *argv[]) {
  printf("main...\n");
  // Nest from main queue > global queue > main queue.
  dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0),
                 ^{
                   dispatch_async(dispatch_get_main_queue(), ^{
                     three();
                   });
                 });
  dispatch_main();
}
"""

    def build(self, filename=None):
        # TEST_PROGRAM is Objective-C, not C/C++, so we can't use the base
        # build() which defaults to main.c / main.cpp + clang/clang++.
        program_path = self.create_file(self.TEST_PROGRAM, "main.m")
        self.run_command(
            [
                "/usr/bin/clang",
                "-g",
                program_path,
                "-o",
                self.getBuildArtifact("a.out"),
            ]
        )

    def build_and_run(self, *, displayExtendedBacktrace: bool = True):
        backtrace_recording_lib = findBacktraceRecordingDylib()
        if not backtrace_recording_lib:
            self.skipTest(
                "Skipped because libBacktraceRecording.dylib was not present on the system."
            )
        if not os.path.isfile("/usr/lib/system/introspection/libdispatch.dylib"):
            self.skipTest(
                "Skipped because introspection libdispatch dylib is not present."
            )

        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = self.getSourcePath("main.m")
        bp_line = line_number(source, "breakpoint 1")

        launch_args = LaunchArgs(
            program=program,
            env=[
                "DYLD_LIBRARY_PATH=/usr/lib/system/introspection",
                f"DYLD_INSERT_LIBRARIES={backtrace_recording_lib}",
            ],
            displayExtendedBacktrace=displayExtendedBacktrace,
        )
        with session.configure(launch_args) as ctx:
            bp_ids = session.resolve_source_breakpoints(source, [bp_line])

        stop_event = session.verify_stopped_on_breakpoint(
            bp_ids, after=ctx.process_event
        )
        return session, stop_event

    @skipUnlessDarwin
    def test_stackTrace(self):
        """Tests the 'stackTrace' packet on a thread with an extended backtrace."""
        session, stop_event = self.build_and_run()
        thread_id = self.expect_not_none(stop_event.body.threadId)

        response = session.stack_trace(thread_id)
        stack_frames = response.body.stackFrames
        total_frames = response.body.totalFrames

        self.assertGreaterEqual(len(stack_frames), 3, "expect >= 3 frames")
        self.assertEqual(len(stack_frames), total_frames)
        self.assertEqual(stack_frames[0].name, "one")
        self.assertEqual(stack_frames[1].name, "two")
        self.assertEqual(stack_frames[2].name, "three")

        stack_labels = [
            (i, frame)
            for i, frame in enumerate(stack_frames)
            if frame.presentationHint == "label"
        ]
        self.assertEqual(len(stack_labels), 2, "expected two label stack frames")
        self.assertRegex(
            stack_labels[0][1].name,
            r"Enqueued from com.apple.root.default-qos \(Thread \d\)",
        )
        self.assertRegex(
            stack_labels[1][1].name,
            r"Enqueued from com.apple.main-thread \(Thread \d\)",
        )

        for i, frame in stack_labels:
            # Ensure requesting startFrame+levels across thread backtraces works as expected.
            response = session.stack_trace(thread_id, startFrame=i - 1, levels=3)
            stack_frames = response.body.stackFrames
            total_frames = self.expect_not_none(response.body.totalFrames)
            self.assertEqual(len(stack_frames), 3, "expected 3 frames with levels=3")
            self.assertGreaterEqual(
                total_frames, i + 3, "total frames should include a pagination offset"
            )
            self.assertEqual(stack_frames[1], frame)

            # Ensure requesting startFrame+levels at the beginning of a thread backtrace works as expected.
            response = session.stack_trace(thread_id, startFrame=i, levels=3)
            stack_frames = response.body.stackFrames
            total_frames = self.expect_not_none(response.body.totalFrames)
            self.assertEqual(len(stack_frames), 3, "expected 3 frames with levels=3")
            self.assertGreaterEqual(
                total_frames, i + 3, "total frames should include a pagination offset"
            )
            self.assertEqual(stack_frames[0], frame)

            # Ensure requests with startFrame+levels that end precisely on the
            # last frame include the totalFrames pagination offset.
            response = session.stack_trace(thread_id, startFrame=i - 1, levels=1)
            stack_frames = response.body.stackFrames
            total_frames = self.expect_not_none(response.body.totalFrames)
            self.assertEqual(len(stack_frames), 1, "expected 1 frame with levels=1")
            self.assertGreaterEqual(
                total_frames, i, "total frames should include a pagination offset"
            )

    @skipUnlessDarwin
    def test_stackTraceWithFormat(self):
        """Tests the 'stackTrace' packet using stack trace formats."""
        session, stop_event = self.build_and_run(displayExtendedBacktrace=False)
        thread_id = self.expect_not_none(stop_event.body.threadId)

        response = session.stack_trace(
            thread_id, format=StackFrameFormat(includeAll=True)
        )

        stack_labels = [
            frame
            for frame in response.body.stackFrames
            if frame.presentationHint == "label"
        ]
        self.assertEqual(len(stack_labels), 2, "expected two label stack frames")
