"""
Test lldb-dap launch request.
"""

import time
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import DisconnectArgs, InitializeArgs
from lldb_dap.session import Session
from lldb_dap.utils import DebugAdapter, DebugAdapterOptions


class TestDAP_launch_termination(DAPTestCaseBase):
    """
    Tests the correct termination of lldb-dap upon a 'disconnect' request.
    """

    def test(self):
        log_file = str(self.test_dir / "launch_termination.log")
        # adapter = DebugAdapter(
        #     executable="/usr/bin/gdb", opts=DebugAdapterOptions(args=["-i", "dap"])
        # )
        adapter = self.create_adapter_in_stdio_mode(DebugAdapterOptions())

        # The underlying lldb-dap process must be alive
        self.assertTrue(adapter.is_alive)
        session = Session(
            self.test_dir,
            adapter,
            self.adapter_timeout,
            log_file=log_file,
        )
        session.start()

        # The lldb-dap process should finish even though
        # we didn't close the communication socket explicitly
        handle = session.send_request(DisconnectArgs())
        response = session.get_response(handle)
        self.assertTrue(response.success)

        # Wait until the underlying lldb-dap process dies.
        # TODO: fix the timeout.
        adapter_process = adapter.process
        adapter_process.wait(timeout=self.adapter_timeout)
        self.assertFalse(session.is_running())

        # Check the return code
        self.assertEqual(adapter_process.poll(), 0)
