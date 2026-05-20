"""
Test lldb-dap runInTerminal reverse request
"""

import json
from typing import cast

from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import (
    Console,
    LaunchArgs,
    RunInTerminalRequest,
)
from lldbsuite.test.decorators import skipIfAsan, skipIfWindows
from lldbsuite.test.lldbtest import line_number


# @skipIfBuildType(["debug"])
class TestDAP_runInTerminal(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False

    TEST_PROGRAM = r"""
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

    def read_pid_message(self, fifo_file):
        with open(fifo_file, "r") as file:
            self.assertIn("pid", file.readline())

    @staticmethod
    def send_did_attach_message(fifo_file):
        with open(fifo_file, "w") as file:
            file.write(json.dumps({"kind": "didAttach"}) + "\n")

    @staticmethod
    def read_error_message(fifo_file):
        with open(fifo_file, "r") as file:
            return file.readline()

    @skipIfAsan
    @skipIfWindows
    def test_runInTerminal(self):
        """
        Tests the "runInTerminal" reverse request. It makes sure that the IDE can
        launch the inferior with the correct environment variables and arguments.
        """
        source = "main.cpp"
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        with session.configure(
            LaunchArgs(
                program,
                console=Console.INTEGRATED_TERMINAL,
                args=["foobar"],
                env=["FOO=bar"],
            )
        ) as ctx:
            breakpoint_line = line_number(source, "// breakpoint")
            session.resolve_source_breakpoints(source, [breakpoint_line])
        process_event = ctx.process_event()

        request = session.last_reverse_request()
        self.assertIsInstance(request, RunInTerminalRequest)
        arguments = cast(RunInTerminalRequest, request).arguments
        self.assertIsNotNone(arguments)
        self.assertIn(self.lldbDAPExec, arguments.args)
        self.assertIn(program, arguments.args)
        self.assertIn("foobar", arguments.args)
        self.assertIn("FOO", arguments.env or {})

        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        thread = session.get_thread_context(stop_event.body.threadId)
        top_frame = thread.top_frame()
        top_frame_id = top_frame.frame.id

        # We verify we actually stopped inside the loop
        counter = top_frame.locals["counter"]
        self.assertEqual(int(counter.value), 1)

        # # We verify we were able to set the launch arguments
        argc = top_frame.locals["argc"]
        self.assertEqual(int(argc.value), 2)

        argv1 = session.evaluate("argv[1]", frameId=top_frame_id).result
        self.assertIn("foobar", argv1)

        # # We verify we were able to set the environment
        env = session.evaluate("foo", frameId=top_frame_id).result
        self.assertIn("bar", env)

        session.continue_to_exit()

    @skipIfAsan
    @skipIfWindows
    def test_runInTerminalWithObjectEnv(self):
        """
        Tests the "runInTerminal" reverse request. It makes sure that the IDE can
        launch the inferior with the correct environment variables using an object.
        """
        program = self.getBuildArtifact("a.out")

        source = self.getBuildArtifact("main.cpp")
        program = self.create_and_compile_file(self.TEST_PROGRAM, source)
        session = self.build_and_create_session()
        session.launch_using_config(
            LaunchArgs(
                program,
                console=Console.INTEGRATED_TERMINAL,
                env={"FOO": "BAR"},
                stopOnEntry=True,
            )
        )

        request = cast(RunInTerminalRequest, session.last_reverse_request())
        self.assertIsInstance(request, RunInTerminalRequest)
        request_envs = self.expect_is_not_none(request.arguments.env)
        self.assertIsNotNone(request_envs)
        self.assertIsInstance(
            request_envs, dict, f"expected dict got {type(request_envs)}"
        )
        self.assertIn("FOO", request_envs)
        self.assertEqual("BAR", request_envs["FOO"])

        session.continue_to_exit()

    @skipIfWindows
    def test_runInTerminalInvalidTarget(self):
        # self.build_and_create_debug_adapter()
        session = self.build_and_create_session()
        launch_handle = session.initialize_and_launch(
            LaunchArgs(
                "INVALIDPROGRAM",
                console=Console.INTEGRATED_TERMINAL,
                args=["foobar"],
                env=["FOO=bar"],
            )
        )

        with self.assertRaises(AssertionError):
            session.verify_configuration_done()

        response = session.get_error_response(launch_handle)

        self.assertFalse(response.success)
        response_body = self.expect_is_not_none(response.body)
        response_error = self.expect_is_not_none(response_body.error)
        self.assertIn("'INVALIDPROGRAM' does not exist", response_error.format)

        session.do_disconnect()
