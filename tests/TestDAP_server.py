"""
Test lldb-dap server integration.
"""

import os
import signal
import tempfile
import time
from concurrent import futures
from unittest import skip

from lldb_dap.dap_types import Event, ExitedEvent, LaunchArgs, TerminatedEvent
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.session_helpers import DAPTestSession
from lldb_dap.utils import DebugAdapterOptions
from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number


class TestDAP_server(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <stdio.h>

int main(int argc, char const *argv[]) {
  if (argc == 2) { // breakpoint 1
    printf("Hello %s!\n", argv[1]);
  } else {
    printf("Hello World!\n");
  }
  return 0; // breakpoint 2
}
"""
    IS_C = True

    def start_server(self, connection: str, connection_timeout: int = 30):
        adapter = self.create_adapter_in_server_mode(
            DebugAdapterOptions(),
            connection=connection,
            connection_timeout=connection_timeout,
        )
        return adapter

    def run_debug_session(
        self, session: DAPTestSession, name: str, *, sleep_seconds_in_middle: float = 0
    ):
        program = self.getBuildArtifact("a.out")
        source = "main.c"
        breakpoint_line = line_number(source, "// breakpoint 1")

        with session.configure(LaunchArgs(program, args=[name])) as ctx:
            session.resolve_source_breakpoints(source, [breakpoint_line])

        if sleep_seconds_in_middle:
            time.sleep(sleep_seconds_in_middle)

        session.verify_stopped_on_breakpoint(after=ctx.process_event())
        session.continue_to_exit()
        output = session.get_stdout()
        self.assertEqual(output, f"Hello {name}!\r\n")

        session.do_disconnect()

    @skipIfWindows
    def test_server_port(self):
        """
        Test launching a binary with a lldb-dap in server mode on a specific port.
        """
        self.build()
        adapter = self.start_server(connection="listen://localhost:0")

        names = ["Alice", "Bob"]
        # Run each session on a different thread.
        with futures.ThreadPoolExecutor() as executor:
            session_args = [(self.create_session(adapter), name) for name in names]
            session_futures = [
                executor.submit(self.run_debug_session, adapter, name)
                for adapter, name in session_args
            ]
            for session_future in futures.as_completed(session_futures):
                session_future.result()

    @skipIfWindows
    @skip("FLAKY")
    def test_server_unix_socket(self):
        """
        Test launching a binary with a lldb-dap in server mode on a unix socket.
        """
        self.build()
        socket_path = f"{tempfile.gettempdir()}/dap-connection-{os.getpid()}"
        self.addTearDownHook(lambda: os.unlink(socket_path))

        adapter = self.start_server(connection="accept://" + socket_path)

        names = ["Alice", "Bob"]
        # Run each session on a different thread.
        with futures.ThreadPoolExecutor() as executor:
            session_args = [(self.create_session(adapter), name) for name in names]
            session_futures = [
                executor.submit(self.run_debug_session, adapter, name)
                for adapter, name in session_args
            ]
            for session_future in futures.as_completed(session_futures):
                session_future.result()

    @skipIfWindows
    def test_server_interrupt(self):
        """
        Test launching a binary with lldb-dap in server mode and shutting down
        the server while the debug session is still active.
        """
        self.build()
        program = self.getBuildArtifact("a.out")
        adapter = self.start_server(connection="listen://localhost:0")
        session = self.create_session(adapter, disconnect_automatically=False)
        source = "main.c"
        breakpoint_line = line_number(source, "// breakpoint 1")

        with session.configure(LaunchArgs(program, args=["Alice"])) as ctx:
            session.resolve_source_breakpoints(source, [breakpoint_line])

        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event())

        # Interrupt the server which should disconnect all clients.
        adapter.process.send_signal(signal.SIGINT)

        # Wait for both events since they can happen in any order.
        seen_events = []

        def seen_both_events(event: Event):
            seen_events.append(event)
            return len(seen_events) == 2

        session.wait_for_any_event(
            (TerminatedEvent, ExitedEvent),
            after=stop_event,
            until=seen_both_events,
            timeout_msg="Process exited before interrupting lldb-dap server",
        )

        exit_code = int(signal.SIGKILL)
        session.verify_process_exited(exitCode=exit_code, after=stop_event)

    @skipIfWindows
    def test_connection_timeout_at_server_start(self):
        # TODO: this is not actually testing it correctly as the server is killed
        # immediately in the teardown hook
        """
        Test launching lldb-dap in server mode with connection timeout and
        waiting for it to terminate automatically when no client connects.
        """
        self.build()
        adapter = self.start_server(
            connection="listen://localhost:0",
            connection_timeout=1,
        )

    @skipIfWindows
    def test_connection_timeout_long_debug_session(self):
        """
        Test launching lldb-dap in server mode with connection timeout and
        terminating the server after the a long debug session.
        """
        self.build()
        adapter = self.start_server(
            connection="listen://localhost:0",
            connection_timeout=1,
        )
        # The connection timeout should not cut off the debug session
        session = self.create_session(adapter)
        self.run_debug_session(session, "Alice", sleep_seconds_in_middle=1.5)
        self.assertTrue(adapter.is_alive, "expected the server to be running")

    @skipIfWindows
    def test_connection_timeout_multiple_sessions(self):
        """
        Test launching lldb-dap in server mode with connection timeout and
        terminating the server after the last debug session.
        """
        self.build()
        adapter = self.start_server(
            connection="listen://localhost:0",
            connection_timeout=1,
        )
        time.sleep(0.5)
        # Should be able to connect to the server.
        session1 = self.create_session(adapter)
        self.run_debug_session(session1, "Alice")
        time.sleep(0.5)
        # Should be able to connect to the server, because it's still within the connection timeout.
        session2 = self.create_session(adapter)
        self.run_debug_session(session2, "Bob")

        time.sleep(1.3)
        # Creating a new session should fail since the connection timeout has passed.
        with self.assertRaises(AssertionError):
            self.create_session(adapter)

    def test_breakpoints_in_multiple_sessions(self):
        """
        Test in server mode setting a breakpoint in one session does not activate
        in another session.
        """
        self.build()
        program = self.getBuildArtifact("a.out")
        adapter = self.start_server("listen://localhost:0", 1)
        session1 = self.create_session(adapter)  # with first breakpoint.
        session2 = self.create_session(adapter)  # with second breakpoint.

        source = "main.c"
        bp1_line = line_number(source, "// breakpoint 1")
        launch_args = LaunchArgs(program)

        # Start the first session and stop at breakpoint 1.
        with session1.configure(launch_args) as ctx1:
            [breakpoint1] = session1.resolve_source_breakpoints(source, [bp1_line])

        session1.verify_stopped_on_breakpoint([breakpoint1], after=ctx1.process_event())

        # Start the second session and stop at breakpoint 2.
        bp2_line = line_number(source, "// breakpoint 2")
        with session2.configure(launch_args) as ctx2:
            [breakpoint2] = session2.resolve_source_breakpoints(source, [bp2_line])

        session2.verify_stopped_on_breakpoint([breakpoint2], after=ctx2.process_event())

        # Start and finish the third session with no breakpoint.
        session3 = self.create_session(adapter)  # with no breakpoint.
        process_event3 = session3.launch_using_config(launch_args)
        session3.verify_process_exited(after=process_event3)

        # Finishing session1 and session2 should not hit any breakpoint.
        session1.continue_to_exit()
        session2.continue_to_exit()
