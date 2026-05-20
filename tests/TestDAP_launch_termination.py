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

    def _test_termination_socket(self):
        adapter = self.create_adapter_in_server_mode(
            DebugAdapterOptions(),
            connection="listen://localhost:0",
            connection_timeout=15,
        )
        self.do_test_termination(adapter)

    def test_termination_stdio(self):
        adapter = self.create_adapter_in_stdio_mode(DebugAdapterOptions())
        self.do_test_termination(adapter)

    def test_termination_multiple_connections(self):
        ...

    def do_test_termination(self, adapter: DebugAdapter):
        # adapter = DebugAdapter("/usr/bin/gdb", DebugAdapterOptions(args=["-i", "dap"]))
        # The underlying lldb-dap process must be alive
        self.assertTrue(adapter.is_alive, f"adapter is dead: {adapter.process.args}")
        session = self.create_session(adapter, disconnect_automatically=False)

        session.initialize_sequence(session.initialize_args)
        # The lldb-dap process should finish even though
        # we didn't close the communication socket explicitly
        session.do_disconnect()

        # Wait until the underlying lldb-dap process dies.
        adapter.process.wait(timeout=self.DEFAULT_TIMEOUT)
        self.assertFalse(session.is_running(), f"expected ended session.")

        # Check the return code
        self.assertEqual(adapter.process.poll(), 0)
