"""
Test lldb-dap cancel request
"""

import os
import time
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import CancelArgs, EvaluateArgs, LaunchArgs

_BUSY_PROGRAM = r'''
import time
import lldb


@lldb.command(command_name="busy-loop")
def busy_loop(debugger, command, exe_ctx, result, internal_dict):
    """Test helper as a busy loop."""
    if not command:
        command = "10"
    count = int(command)
    print("Starting loop...", count)
    for i in range(count):
        if debugger.InterruptRequested():
            print("interrupt requested, stopping loop", i)
            break
        print("No interrupted requested, sleeping", i)
        time.sleep(1)

'''


class TestDAP_cancel(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <stdio.h>

int main(int argc, char const *argv[]) {
  printf("Hello world!\n");
  return 0;
}

"""

    def async_blocking_request(self, count: int):
        """
        Sends an evaluate request that will sleep for the specified count to
        block the request handling thread.
        """
        return self.session.send_request(
            EvaluateArgs(expression=f"`busy-loop {count}", context="repl")
        )

    def async_cancel(self, requestId: int):
        return self.session.send_request(CancelArgs(requestId=requestId))

    def test_pending_request(self):
        """
        Tests cancelling a pending request.
        """
        # program = self.getBuildArtifact("a.out")
        # busy_loop = self.getSourcePath("busy_loop.py")
        program = self.create_test_program_with_name("main.cpp")
        busy_loop = self.create_file(_BUSY_PROGRAM, "busy_loop.py")
        process_event, _ = self.session.launch_using_config(
            LaunchArgs(
                program,
                initCommands=[f"command script import {busy_loop}"],
                stopOnEntry=True,
            )
        )
        self.session.verify_stopped_on_entry(after=process_event)

        # Use a relatively short timeout since this is only to ensure the
        # following request is queued.
        blocking_handle = self.async_blocking_request(count=1)
        # Use a longer timeout to ensure we catch if the request was interrupted
        # properly.
        pending_handle = self.async_blocking_request(count=10)
        cancel_handle = self.async_cancel(requestId=pending_handle.seq)
        self.session.verify_configuration_done

        blocking_resp = self.session.get_response(blocking_handle)
        self.assertEqual(blocking_resp.request_seq, blocking_handle.seq)
        self.assertEqual(blocking_resp.command, "evaluate")
        self.assertEqual(blocking_resp.success, True)

        pending_resp = self.session.get_error_response(pending_handle)
        self.assertEqual(pending_resp.request_seq, pending_handle.seq)
        self.assertEqual(pending_resp.command, "evaluate")
        self.assertEqual(pending_resp.success, False)
        self.assertEqual(pending_resp.message, "cancelled")

        cancel_resp = self.session.get_response(cancel_handle)
        self.assertEqual(cancel_resp.request_seq, cancel_handle.seq)
        self.assertEqual(cancel_resp.command, "cancel")
        self.assertEqual(cancel_resp.success, True)
        self.session.continue_to_exit()

    def test_inflight_request(self):
        """Tests cancelling an inflight request."""
        program = self.create_test_program_with_name("main.cpp")
        busy_loop = self.create_file(_BUSY_PROGRAM, "busy_loop.py")
        # program = self.getBuildArtifact("a.out")
        # busy_loop = self.getSourcePath("busy_loop.py")
        process_event, _ = self.session.launch_using_config(
            LaunchArgs(
                program,
                initCommands=[f"command script import {busy_loop}"],
                stopOnEntry=True,
            )
        )
        self.session.verify_stopped_on_entry(after=process_event)

        blocking_handle = self.async_blocking_request(count=10)
        # Wait for the sleep to start to cancel the inflight request.
        time.sleep(0.5)
        cancel_handle = self.async_cancel(requestId=blocking_handle.seq)

        blocking_resp = self.session.get_error_response(blocking_handle)
        self.assertEqual(blocking_resp.request_seq, blocking_handle.seq)
        self.assertEqual(blocking_resp.command, "evaluate")
        self.assertEqual(blocking_resp.success, False)
        self.assertEqual(blocking_resp.message, "cancelled")

        cancel_resp = self.session.get_response(cancel_handle)
        self.assertEqual(cancel_resp.request_seq, cancel_handle.seq)
        self.assertEqual(cancel_resp.command, "cancel")
        self.assertEqual(cancel_resp.success, True)
        self.session.continue_to_exit()
