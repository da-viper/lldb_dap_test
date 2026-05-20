"""
Test lldb-dap source request
"""


from lldb_dap.dap_types import LaunchArgs, SourceArgs, StackTraceArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number


class TestDAP_source(DAPTestCaseBase):
    TEST_PROGRAM = r"""#include <stdio.h>

__attribute__((nodebug)) static void add(int i, int j, void handler(int)) {
  handler(i + j);
}

static void handler(int result) {
  printf("result %d\n", result); // first_frame, breakpoint 
}

int main(int argc, char const *argv[]) {
  add(2, 3, handler); // third_frame
  return 0;
}

"""
    IS_C = True

    @skipIfWindows
    def test_source(self):
        """
        Tests the 'source' packet.
        """
        program = self.getBuildArtifact("a.out")
        source = self.getSourcePath("main.c")
        session = self.build_and_create_session()
        with session.configure(LaunchArgs(program)) as ctx:
            breakpoint_line = line_number(source, "breakpoint")
            lines = [breakpoint_line]
            breakpoint_ids = session.resolve_source_breakpoints(source, lines)
            self.assertEqual(
                len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
            )

        stop_event = session.verify_stopped_on_breakpoint(
            breakpoint_ids, after=ctx.process_event()
        )

        response = session.request_and_error_response(SourceArgs(sourceReference=0))
        self.assertFalse(response.success, "verify invalid sourceReference fails")

        thread_id = self.expect_is_not_none(stop_event.body.threadId)
        response = session.request_and_respond(StackTraceArgs(thread_id))

        stack_frames = response.body.stackFrames
        total_frames = response.body.totalFrames
        frame_count = len(stack_frames)
        self.assertGreaterEqual(frame_count, 3, "verify we got up to main at least")
        self.assertEqual(
            total_frames,
            frame_count,
            "verify total frames returns a speculative page size",
        )
        want_frames = [
            {
                "name": "handler",
                "line": line_number(source, "first_frame"),
                "source": {
                    "name": "main.c",
                    "path": source,
                    "containsSourceReference": False,
                },
            },
            {
                "name": "add",
                "source": {
                    "name": "add",
                    "path": program + "`add",
                    "containsSourceReference": True,
                },
            },
            {
                "name": "main",
                "line": line_number(source, "third_frame"),
                "source": {
                    "name": "main.c",
                    "path": source,
                    "containsSourceReference": False,
                },
            },
        ]

        for want, frame in zip(want_frames, stack_frames):
            self.assertEqual(frame.name, want["name"])

            if "line" in want:
                self.assertEqual(frame.line, want["line"])

            want_source = want["source"]
            frame_source = self.expect_is_not_none(frame.source)
            self.assertEqual(frame_source.name, want_source["name"])

            self.assertEqual(frame_source.path, want_source["path"])

            if want_source["containsSourceReference"]:
                source_reference = self.expect_is_not_none(frame_source.sourceReference)
                source_response = session.request_and_respond(
                    SourceArgs(source_reference)
                )
                self.assertGreater(
                    len(source_response.body.content),
                    0,
                    "verify content returned disassembly",
                )
                self.assertEqual(
                    source_response.body.mimeType,
                    "text/x-lldb.disassembly",
                    "verify mime type returned",
                )
            else:
                self.assertIsNone(frame_source.sourceReference)
