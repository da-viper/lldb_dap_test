"""
Test lldb-dap stack trace response
"""


from lldb_dap import lldb_dap_testcase
from lldb_dap.dap_types import LaunchArgs, StackTraceArgs
from lldbsuite.test.decorators import add_test_categories
from lldbsuite.test.lldbtest import line_number


class TestDAP_subtleFrames(lldb_dap_testcase.DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <functional>
#include <iostream>

void greet() {
  // BREAK HERE
  std::cout << "Hello\n";
}

int main() {
  std::function<void()> func{greet};
  func();
  return 0;
}
"""
    def build(self):
        file = self.create_file(self.TEST_PROGRAM, "main.cpp")
        return self.compile_program(file, extra_args=["-stdlib=libc++"])

    @add_test_categories(["libc++"])
    def test_subtleFrames(self):
        """
        Internal stack frames (such as the ones used by `std::function`) are marked as "subtle".
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = "main.cpp"
        with session.configure(LaunchArgs(program)) as ctx:
            bps = session.resolve_source_breakpoints(
                source, [line_number(source, "BREAK HERE")]
            )

        stop_event = session.verify_stopped_on_breakpoint(
            bps, after=ctx.process_event()
        )

        thread_id = self.expect_is_not_none(stop_event.body.threadId)
        resp = session.request_and_respond(StackTraceArgs(thread_id))
        frames = resp.body.stackFrames
        for f in frames:
            if "__function" in f.name:
                self.assertEqual(f.presentationHint, "subtle")
        self.assertTrue(any(f.presentationHint == "subtle" for f in frames))

        session.continue_to_exit()
