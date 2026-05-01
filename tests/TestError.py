from dataclasses import dataclass
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import (
    ContinueArgs,
    ErrorResponse,
    LaunchArgs,
    StackTraceArgs,
    args_protocol,
)


class TestErrorHandling(DAPTestCaseBase):
    """Test error handling"""

    def test_invalid_command(self):
        @dataclass
        @args_protocol
        class InvalidArgs:
            command_ = "invalidCommand"
            response_class_ = ErrorResponse

        """Test handling of invalid command"""
        handle = self.session.send_request(InvalidArgs())
        response = self.session.get_error_response(handle)
        self.assertIsNotNone(response.body)
        self.assertIsNotNone(response.body.error)
        self.assertEqual(response.body.error.format, "unknown request")

    def test_request_before_initialize(self):
        """Test that requests before initialize fail appropriately"""
        handle = self.session.send_request(ContinueArgs())
        response = self.session.get_error_response(handle)
        self.assertEqual(response.message, "notStopped")

    # TODO: reenable
    def test_invalid_thread_id(self):
        """Test operations with invalid thread ID"""
        test_program = self.create_and_compile_file("int main() { return 0; }\n")

        session = self.session
        with session.configure(LaunchArgs(program=test_program)) as ctx:
            session.set_source_breakpoints("main.cpp", [1])

        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event())

        # Try to get stack trace with invalid thread ID
        handle = self.session.send_request(StackTraceArgs(threadId=9999))
        with self.assertRaises(AssertionError):
            self.session.get_response(handle)

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        thread_ctx.top_frame().scopes()
        session.continue_to_exit()
