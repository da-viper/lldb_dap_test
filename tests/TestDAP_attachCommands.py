"""
Test lldb-dap attach commands
"""

from lldbsuite.test.decorators import skipIfNetBSD
from lldbsuite.test.tools.lldb_dap.types import AttachArgs, PauseArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase

ATTACH_H = r"""
#ifndef LLDB_TEST_ATTACH_H
#define LLDB_TEST_ATTACH_H

// On some systems (e.g., some versions of linux) it is not possible to attach
// to a process without it giving us special permissions. This defines the
// lldb_enable_attach macro, which should perform any such actions, if needed by
// the platform.
#if defined(__linux__)
#include <sys/prctl.h>

// Android API <= 16 does not have these defined.
#ifndef PR_SET_PTRACER
#define PR_SET_PTRACER 0x59616d61
#endif
#ifndef PR_SET_PTRACER_ANY
#define PR_SET_PTRACER_ANY ((unsigned long)-1)
#endif

// For now we execute on best effort basis.  If this fails for some reason, so
// be it.
#define lldb_enable_attach()                                                   \
  do {                                                                         \
    const int prctl_result =                                                   \
        prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0);                    \
    (void)prctl_result;                                                        \
  } while (0)

#else // not linux

#define lldb_enable_attach()

#endif // defined(__linux__)

#endif // LLDB_TEST_ATTACH_H
"""


class TestDAP_attachCommands(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False

    TEST_PROGRAM = r"""
#include "attach.h"
#ifdef _WIN32 
#include <windows.h> 
#define sleep_ms(ms) Sleep(ms) 
#else 
#include <unistd.h> 
#define sleep_ms(ms) usleep((ms) * 1000) 
#endif

volatile int is_ready = 0;

int main(int argc, char const *argv[]) {
  lldb_enable_attach();

  while (!is_ready) {
    sleep_ms(50); // breakpoint 1
  }

  return 0; 
}
"""
    IS_C = True

    def build(self, dictionary=None):
        self.create_file(ATTACH_H, "attach.h")
        super().build(dictionary)

    @skipIfNetBSD  # Hangs on NetBSD as well
    def test_commands(self):
        """
        Tests the "initCommands", "preRunCommands", "stopCommands",
        "exitCommands", "terminateCommands" and "attachCommands"
        that can be passed during attach.

        "initCommands" are a list of LLDB commands that get executed
        before the target is created.
        "preRunCommands" are a list of LLDB commands that get executed
        after the target has been created and before the launch.
        "stopCommands" are a list of LLDB commands that get executed each
        time the program stops.
        "exitCommands" are a list of LLDB commands that get executed when
        the process exits
        "attachCommands" are a list of LLDB commands that get executed and
        must have a valid process in the selected target in LLDB after
        they are done executing. This allows custom commands to create any
        kind of debug session.
        "terminateCommands" are a list of LLDB commands that get executed when
        the debugger session terminates.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()

        # Here we just create a target and launch the process as a way to test
        # if we are able to use attach commands to create any kind of a target
        # and use it for debugging.
        attachCommands = [
            f'target create -d "{program}"',
            "process launch --stop-at-user-entry",
        ]
        initCommands = ["target list", "platform list"]
        preRunCommands = ["image list a.out", "image dump sections a.out"]
        postRunCommands = ["help trace", "help process trace"]
        stopCommands = ["frame variable", "thread backtrace"]
        exitCommands = ["history -c 2"]
        terminateCommands = ["platform status"]

        process_event = session.attach(
            AttachArgs(
                program=program,
                attachCommands=attachCommands,
                stopOnEntry=True,
                initCommands=initCommands,
                preRunCommands=preRunCommands,
                stopCommands=stopCommands,
                exitCommands=exitCommands,
                terminateCommands=terminateCommands,
                postRunCommands=postRunCommands,
            )
        )

        # Get output from the console. This should contain both the
        # "initCommands" and the "preRunCommands".
        output = session.get_console()
        # Verify all "initCommands" were found in console output
        session.verify_commands("initCommands", output, initCommands)
        # Verify all "preRunCommands" were found in console output
        session.verify_commands("preRunCommands", output, preRunCommands)
        # Verify all "postRunCommands" were found in console output
        session.verify_commands("postRunCommands", output, postRunCommands)

        stopped_event = session.verify_stopped_on_entry(after=process_event)
        stopped_thread_id = self.expect_not_none(stopped_event.body.threadId)

        output = session.collect_console(after=stopped_event, until=stopCommands[-1])
        session.verify_commands("stopCommands", output.seen_texts, stopCommands)

        # Continue after launch and hit the "pause()" call and stop the target.
        # Get output from the console. This should contain both the
        # "stopCommands" that were run after we stop.
        session.do_continue()

        before_pause = session.last_event()
        session.send_request(PauseArgs(stopped_thread_id)).result()
        session.wait_for_stopped_event(after=before_pause)

        output = session.collect_console(after=before_pause, until=stopCommands[-1])
        session.verify_commands("stopCommands", output.seen_texts, stopCommands)

        # Continue until the program exits.
        session.evaluate("`expression is_ready = 1", context="repl")
        session.continue_to_exit()

        # Get output from the console. This should contain both the
        # "exitCommands" that were run after the second breakpoint was hit
        # and the "terminateCommands" due to the debugging session ending
        output = session.collect_console(after=output.event, until=terminateCommands[0])
        output_texts = output.seen_texts
        session.verify_commands("exitCommands", output_texts, exitCommands)
        session.verify_commands("terminateCommands", output_texts, terminateCommands)

    def test_attach_command_process_failures(self):
        """
        Tests that a 'attachCommands' is expected to leave the debugger's
        selected target with a valid process.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()

        attach_args = AttachArgs(
            program=program,
            attachCommands=['script print("oops, forgot to attach to a process...")'],
        )
        pending_attach = session.send_request(attach_args)
        session.verify_configuration_done(expected_success=False)

        attach_response = pending_attach.error()
        response_body = self.expect_not_none(attach_response.body)
        response_error = self.expect_not_none(response_body.error)
        self.assertIn(
            "attachCommands failed to attach to a process", response_error.format
        )

    @skipIfNetBSD  # Hangs on NetBSD as well
    def test_terminate_commands(self):
        # TODO: do not use expression in terminate commands.
        """
        Tests that the "terminateCommands", that can be passed during
        attach, are run when the debugger is disconnected.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session(disconnect_automatically=False)

        # Here we just create a target and launch the process as a way to test
        # if we are able to use attach commands to create any kind of a target
        # and use it for debugging
        attachCommands = [
            f"target create -d '{program}'",
            "process launch --stop-at-user-entry",
        ]
        terminateCommands = ["history -c 1"]
        process_event = session.attach(
            AttachArgs(
                program=program,
                attachCommands=attachCommands,
                terminateCommands=terminateCommands,
            )
        )
        # Once it's disconnected the console should contain the "terminateCommands".
        session.disconnect(terminateDebuggee=True)
        output = session.collect_console(
            after=process_event, until=terminateCommands[0]
        )
        session.verify_commands(
            "terminateCommands", output.seen_texts, terminateCommands
        )
