"""
Test lldb-dap attach commands
"""

import time
from typing import cast

from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import AttachArgs, PauseArgs, StoppedReason

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

    # TODO: NOTE THE SLEEP function is removed do the same when up-streaming it.
    TEST_PROGRAM = r"""
#include "attach.h"
#include <stdio.h>
#ifdef _WIN32
#include <process.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

int main(int argc, char const *argv[]) {
lldb_enable_attach();

  if (argc >= 2) {
    // Create the synchronization token.
    FILE *f = fopen(argv[1], "wx");
    if (!f)
      return 1;
    fputs("\n", f);
    fflush(f);
    fclose(f);
  }

  int is_first_time = 1;
  volatile int ready = 0;
  while (!ready) {
    if (is_first_time) { 
        // we use the printed pid to synchronize when change the ready variable in the debugger.
        puts("infinite loop started");
        is_first_time = 0;
    }
  }
  return 0; // breakpoint 1
}
"""

    # @skipIfNetBSD  # Hangs on NetBSD as well TODO:
    def _test_commands(self):
        # TODO: this test is still flaky and it is not because of dap but the pause
        # I don't need to stop the process again after a pause.
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
        session = self.session
        self.create_file(ATTACH_H, "attach.h")
        program = self.create_test_program_with_name("main.cpp")

        # Here we just create a target and launch the process as a way to test
        # if we are able to use attach commands to create any kind of a target
        # and use it for debugging
        attachCommands = [
            f'target create -d "{program}"',
            "process launch --stop-at-user-entry",
        ]
        initCommands = ["target list", "platform list"]
        preRunCommands = ["image list a.out", "image dump sections a.out"]
        postRunCommands = ["help trace", "help process trace"]
        stopCommands = ["frame variable", "thread backtrace"]
        exitCommands = ["expr 2+3", "expr 3+4"]
        terminateCommands = ["expr 4+2"]

        process_event, _ = session.attach_using_config(
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
        self.assertIsNotNone(stopped_event.body.threadId)
        stopped_thread_id = cast(int, stopped_event.body.threadId)

        output = session.collect_console_until(stopCommands[-1], after=stopped_event)
        session.verify_commands("stopCommands", output.seen_texts, stopCommands)

        # Continue after launch and hit the "pause()" call and stop the target.
        # Get output from the console. This should contain both the
        # "stopCommands" that were run after we stop.
        session.do_continue()

        # use the printed pid to synchronize when change the ready variable.
        session.collect_stdout_until("infinite loop started", after=output.event)
        pause_response = session.request_and_respond(PauseArgs(stopped_thread_id))
        stopped_event = session.wait_for_stopped(after=pause_response)

        output = session.collect_console_until(stopCommands[-1], after=output.event)
        session.verify_commands("stopCommands", output.seen_texts, stopCommands)

        # set the ready variable so that the process can continue to exit.
        session.evaluate("`expr ready = 1")

        # Continue until the program exits
        session.continue_to_exit()

        # Get output from the console. This should contain both the
        # "exitCommands" that were run after the second breakpoint was hit
        # and the "terminateCommands" due to the debugging session ending
        output = session.collect_console_until(terminateCommands[0], after=output.event)
        session.verify_commands("exitCommands", output.seen_texts, exitCommands)
        session.verify_commands(
            "terminateCommands", output.seen_texts, terminateCommands
        )

    def test_attach_command_process_failures(self):
        """
        Tests that a 'attachCommands' is expected to leave the debugger's
        selected target with a valid process.
        """
        self.create_file(ATTACH_H, "attach.h")
        program = self.create_test_program_with_name("main.cpp")
        session = self.session

        attachCommands = ['script print("oops, forgot to attach to a process...")']
        attach_args = AttachArgs(
            program=program,
            attachCommands=attachCommands,
        )
        attach_handle = session.send_request(attach_args)
        with self.assertRaises(Exception):  # TODO: specialize exception
            session.verify_configuration_done()

        attach_response = session.get_error_response(attach_handle)
        self.assertFalse(attach_response.success)
        response_error = self.expect_is_not_none(attach_response.body.error)
        self.assertIn(
            "attachCommands failed to attach to a process", response_error.format
        )

    # @skipIfNetBSD  # Hangs on NetBSD as well
    def test_terminate_commands(
        self,
    ):  # TODO: do not use expression terminate commands.
        """
        Tests that the "terminateCommands", that can be passed during
        attach, are run when the debugger is disconnected.
        """
        self.create_file(ATTACH_H, "attach.h")
        program = self.create_test_program_with_name("main.cpp")
        session = self.session

        # Here we just create a target and launch the process as a way to test
        # if we are able to use attach commands to create any kind of a target
        # and use it for debugging
        attachCommands = [
            'target create -d "%s"' % (program),
            "process launch --stop-at-user-entry",
        ]
        terminateCommands = ["history -c 1"]
        process_event, _ = session.attach_using_config(
            AttachArgs(
                program=program,
                attachCommands=attachCommands,
                terminateCommands=terminateCommands,
            )
        )
        # Once it's disconnected the console should contain the
        # "terminateCommands"
        session.disconnect(terminateDebuggee=True)
        output = session.collect_console_until(
            terminateCommands[0], after=process_event
        )
        session.verify_commands(
            "terminateCommands", output.seen_texts, terminateCommands
        )
