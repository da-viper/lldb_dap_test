from __future__ import annotations

"""
Test lldb-dap runInTerminal reverse request and the --launch-target launcher.
"""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from typing import Iterator, cast

from lldbsuite.test.decorators import skipIfAsan, skipIfBuildType, skipIfWindows
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.dap_types import (
    Console,
    ErrorResponse,
    LaunchArgs,
    RunInTerminalRequest,
)
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase

if sys.platform == "win32":
    import ctypes

    class FifoComm:
        """Bidirectional channel — Windows named pipe."""

        PIPE_NAME = r"\\.\pipe\lldb-dap-run-in-terminal-comm"

        # Win32 constants for CreateNamedPipeW.
        _PIPE_ACCESS_DUPLEX = 0x00000003
        _PIPE_TYPE_MESSAGE = 0x00000004
        _PIPE_READMODE_MESSAGE = 0x00000002
        _PIPE_WAIT = 0x00000000
        _PIPE_UNLIMITED_INSTANCES = 255
        _ERROR_MORE_DATA = 234

        def __init__(self, pipe_handle):
            self._pipe = pipe_handle

        @classmethod
        def create(cls, directory: str) -> "FifoComm":
            del directory  # unused on Windows
            kernel32 = ctypes.windll.kernel32
            pipe = kernel32.CreateNamedPipeW(
                cls.PIPE_NAME,
                cls._PIPE_ACCESS_DUPLEX,
                cls._PIPE_TYPE_MESSAGE | cls._PIPE_READMODE_MESSAGE | cls._PIPE_WAIT,
                cls._PIPE_UNLIMITED_INSTANCES,
                4096,
                4096,
                0,
                None,
            )
            return cls(pipe)

        @property
        def comm_file(self) -> str:
            return self.PIPE_NAME

        def read_message(self) -> str:
            ctypes.windll.kernel32.ConnectNamedPipe(self._pipe, None)
            kernel32 = ctypes.windll.kernel32
            buffer = b""
            while True:
                chunk = ctypes.create_string_buffer(4096)
                bytes_read = ctypes.wintypes.DWORD()
                success = kernel32.ReadFile(
                    self._pipe, chunk, 4096, ctypes.byref(bytes_read), None
                )
                buffer += chunk.raw[: bytes_read.value]
                if success:
                    break
                if ctypes.GetLastError() != self._ERROR_MORE_DATA:
                    break
            return buffer.decode()

        def write_message(self, message: str) -> None:
            kernel32 = ctypes.windll.kernel32
            kernel32.ConnectNamedPipe(self._pipe, None)
            bytes_written = ctypes.wintypes.DWORD()
            kernel32.WriteFile(
                self._pipe,
                message.encode(),
                len(message),
                ctypes.byref(bytes_written),
                None,
            )

        def close(self) -> None:
            kernel32 = ctypes.windll.kernel32
            kernel32.DisconnectNamedPipe(self._pipe)
            kernel32.CloseHandle(self._pipe)

else:

    class FifoComm:
        """Bidirectional channel — POSIX FIFO."""

        def __init__(self, comm_file: str):
            self._comm_file = comm_file

        @classmethod
        def create(cls, directory: str) -> "FifoComm":
            comm_file = os.path.join(directory, "comm-file")
            os.mkfifo(comm_file)
            return cls(comm_file)

        @property
        def comm_file(self) -> str:
            return self._comm_file

        def read_message(self) -> str:
            with open(self._comm_file, "r") as f:
                return f.readline()

        def write_message(self, message: str) -> None:
            with open(self._comm_file, "w") as f:
                f.write(message)

        def close(self) -> None:
            pass


@contextmanager
def fifo_comm(directory: str) -> Iterator[FifoComm]:
    """Open a `FifoComm` appropriate for the current platform."""
    comm = FifoComm.create(directory)
    try:
        yield comm
    finally:
        comm.close()


_TEST_PROGRAM = r"""
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <stdlib.h>
#else
#include <unistd.h>
#endif

int main(int argc, char *argv[]) {
  const char *foo = getenv("FOO");
  int counter = 1;

  return 0; // breakpoint
}
"""


@skipIfBuildType(["debug"])
@skipIfWindows  # https://github.com/llvm/llvm-project/issues/198763
class TestDAP_runInTerminal(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False
    IS_C = True
    TEST_PROGRAM = _TEST_PROGRAM

    @skipIfAsan
    def test_runInTerminal(self):
        """The IDE can launch the inferior with the right env and args."""
        program = self.getBuildArtifact("a.out")
        source = "main.c"
        session = self.build_and_create_session()

        launch_args = LaunchArgs(
            program=program,
            console=Console.INTEGRATED_TERMINAL,
            args=["foobar"],
            env=["FOO=bar"],
        )
        with session.configure(launch_args) as ctx:
            breakpoint_line = line_number(source, "// breakpoint")
            session.resolve_source_breakpoints(source, [breakpoint_line])

        request = session.last_reverse_request()
        self.assertIsInstance(request, RunInTerminalRequest)
        arguments = cast(RunInTerminalRequest, request).arguments
        self.assertIsNotNone(arguments)
        self.assertIn(self.lldbDAPExec, arguments.args)
        self.assertIn(program, arguments.args)
        self.assertIn("foobar", arguments.args)
        self.assertIn("FOO", arguments.env or {})

        stop_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)
        thread_id = self.expect_not_none(stop_event.body.threadId)
        frame = session.top_frame_from(thread_id)

        # Verify we stopped inside main.
        self.assertEqual(frame.locals["counter"].value_as_int, 1)
        # Verify launch arguments.
        self.assertEqual(frame.locals["argc"].value_as_int, 2)
        self.assertIn("foobar", frame.evaluate("argv[1]").result)

        # Verify program arguments.
        self.assertIn("bar", frame.evaluate("foo").result)

        session.continue_to_exit()

    @skipIfAsan
    def test_runInTerminalWithObjectEnv(self):
        """`env` passed as a dict object reaches the runInTerminal request."""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        session.launch(
            LaunchArgs(
                program,
                console=Console.INTEGRATED_TERMINAL,
                env={"FOO": "BAR"},
                stopOnEntry=True,
            )
        )

        request = cast(RunInTerminalRequest, session.last_reverse_request())
        self.assertIsInstance(request, RunInTerminalRequest)
        request_envs = self.expect_not_none(request.arguments.env)
        self.assertIsNotNone(request_envs)
        self.assertIsInstance(
            request_envs, dict, f"expected dict got {type(request_envs)}"
        )
        self.assertIn("FOO", request_envs)
        self.assertEqual("BAR", request_envs["FOO"])

        session.continue_to_exit()

    @skipIfWindows
    def test_runInTerminalInvalidTarget(self):
        session = self.create_session()
        launch_handle = session.initialize_and_launch(
            LaunchArgs(
                program="INVALIDPROGRAM",
                console=Console.INTEGRATED_TERMINAL,
                args=["foobar"],
                env=["FOO=bar"],
            )
        )
        session.verify_configuration_done(expected_success=False)
        response = launch_handle.error()

        self.assertFalse(response.success)
        response_body = self.expect_not_none(response.body)
        response_error = self.expect_not_none(response_body.error)
        self.assertIn("'INVALIDPROGRAM' does not exist", response_error.format)

    def test_client_missing_runInTerminal_feature(self):
        """A client that lacks `supportsRunInTerminalRequest` gets a clear error."""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        session.update_initialize_args(supportsRunInTerminalRequest=False)

        session.initialize_sequence(session.initialize_args)
        handle = session.send_request(
            LaunchArgs(program=program, console=Console.INTEGRATED_TERMINAL)
        )

        session.verify_configuration_done(expected_success=False)

        response = handle.result_or_error()
        self.assertIsInstance(response, ErrorResponse)
        response_body = self.expect_not_none(response.body)
        error = self.expect_not_none(response_body.error)
        self.assertIn("Client does not support RunInTerminal.", error.format)



# TODO: Separate Tests that exercise `lldb-dap --launch-target` directly. 
# So the entire test do not use the USE_DEFAULT_DEBUG_ADAPTER.
# These tests do not need a debug adapter  they just spawn the binary and talk to it through

@skipIfBuildType(["debug"])
@skipIfWindows  # https://github.com/llvm/llvm-project/issues/198763
class TestDAP_runInTerminalLauncher(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False
    USE_DEFAULT_DEBUG_ADAPTER = False
    NO_DEBUG_INFO_TESTCASE = True

    def _send_did_attach(self, comm: FifoComm) -> None:
        comm.write_message(json.dumps({"kind": "didAttach"}) + "\n")

    def test_missingArgInRunInTerminalLauncher(self):
        """`--launch-target` requires a `--comm-file`."""
        proc = subprocess.run(
            [self.lldbDAPExec, "--launch-target", "INVALIDPROGRAM"],
            capture_output=True,
            universal_newlines=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(
            '"--launch-target" requires "--comm-file" to be specified',
            proc.stderr,
        )

    def test_FakeAttachedRunInTerminalLauncherWithInvalidProgram(self):
        with fifo_comm(self.getBuildDir()) as comm:
            proc = subprocess.Popen(
                [
                    self.lldbDAPExec,
                    "--comm-file",
                    comm.comm_file,
                    "--launch-target",
                    "INVALIDPROGRAM",
                ],
                universal_newlines=True,
                stderr=subprocess.PIPE,
            )
            if sys.platform == "win32":
                _, stderr = proc.communicate()
                self.assertIn("Failed to launch target process", stderr)
            else:
                self.assertIn("pid", comm.read_message())
                self._send_did_attach(comm)
                self.assertIn(
                    "No such file or directory",
                    comm.read_message(),
                )

                _, stderr = proc.communicate()
                self.assertIn("No such file or directory", stderr)

    def test_FakeAttachedRunInTerminalLauncherWithValidProgram(self):
        with fifo_comm(self.getBuildDir()) as comm:
            proc = subprocess.Popen(
                [
                    self.lldbDAPExec,
                    "--comm-file",
                    comm.comm_file,
                    "--launch-target",
                    "echo",
                    "foo",
                ],
                universal_newlines=True,
                stdout=subprocess.PIPE,
            )

            self.assertIn("pid", comm.read_message())
            self._send_did_attach(comm)

            stdout, _ = proc.communicate()

        self.assertIn("foo", stdout)

    def test_FakeAttachedRunInTerminalLauncherAndCheckEnvironment(self):
        with fifo_comm(self.getBuildDir()) as comm:
            proc = subprocess.Popen(
                [
                    self.lldbDAPExec,
                    "--comm-file",
                    comm.comm_file,
                    "--launch-target",
                    "env",
                ],
                universal_newlines=True,
                stdout=subprocess.PIPE,
                env={**os.environ, "FOO": "BAR"},
            )

            self.assertIn("pid", comm.read_message())
            self._send_did_attach(comm)

            stdout, _ = proc.communicate()

        self.assertIn("FOO=BAR", stdout)

    def test_NonAttachedRunInTerminalLauncher(self):
        """Without a didAttach acknowledgement the launcher times out."""
        with fifo_comm(self.getBuildDir()) as comm:
            proc = subprocess.Popen(
                [
                    self.lldbDAPExec,
                    "--comm-file",
                    comm.comm_file,
                    "--launch-target",
                    "echo",
                    "foo",
                ],
                universal_newlines=True,
                stderr=subprocess.PIPE,
                env={**os.environ, "LLDB_DAP_RIT_TIMEOUT_IN_MS": "500"},
            )

            self.assertIn("pid", comm.read_message())

            _, stderr = proc.communicate()

        self.assertIn(
            "Timed out trying to get messages from the debug adapter",
            stderr,
        )
