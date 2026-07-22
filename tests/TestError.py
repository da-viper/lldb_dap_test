from dataclasses import dataclass

from lldbsuite.test.tools.lldb_dap.types import (
    ContinueArgs,
    ErrorResponse,
    LaunchArgs,
    StackTraceArgs,
    args_protocol,
)
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestErrorHandling(DAPTestCaseBase):
    """Test error handling"""

    TEST_PROGRAM = r"""int main() { return 0; }"""

    def test_invalid_command(self):
        """Test handling of invalid command"""

        @dataclass
        @args_protocol
        class InvalidArgs:
            command_ = "invalidCommand"
            response_class_ = ErrorResponse

        session = self.create_session()
        handle = session.send_request(InvalidArgs())
        response = handle.error()
        response_body = self.expect_not_none(response.body)
        response_error = self.expect_not_none(response_body.error)
        self.assertEqual(response_error.format, "unknown request")

    def test_request_before_initialize(self):
        """Test that requests before initialize fail appropriately"""
        session = self.create_session()
        handle = session.send_request(ContinueArgs(12345))
        response = handle.error()
        self.assertEqual(response.message, "notStopped")

    def test_invalid_thread_id(self):
        """Test operations with invalid thread ID"""
        test_program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()

        with session.configure(LaunchArgs(program=test_program)) as ctx:
            session.set_source_breakpoints("main.cpp", [1])

        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)

        # Try to get stack trace with invalid thread ID.
        handle = session.send_request(StackTraceArgs(threadId=9999))
        handle.error()

        thread_ctx = session.thread_context_from(stop_event)
        thread_ctx.top_frame().scopes()
        session.continue_to_exit()
