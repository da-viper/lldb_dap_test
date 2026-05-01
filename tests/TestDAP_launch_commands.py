"""
Test lldb-dap launch request.
"""

# from lldbsuite.test.decorators import skipIf
# # from lldbsuite.test.lldbtest import line_number
# import lldbdap_testcase


import unittest
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number
from lldb_dap.dap_types import InitializedEvent, LaunchArgs


class TestDAP_launch_commands(DAPTestCaseBase):
    """
    Tests the "initCommands", "preRunCommands", "stopCommands",
    "terminateCommands" and "exitCommands" that can be passed during
    launch.

    "initCommands" are a list of LLDB commands that get executed
    before the target is created.
    "preRunCommands" are a list of LLDB commands that get executed
    after the target has been created and before the launch.
    "stopCommands" are a list of LLDB commands that get executed each
    time the program stops.
    "exitCommands" are a list of LLDB commands that get executed when
    the process exits
    "terminateCommands" are a list of LLDB commands that get executed when
    the debugger session terminates.
    """

    # @skipIf(archs=["arm$", "aarch64"], bugnumber=6933)
    def test(self):
        program = self.create_test_program_with_name("main.cpp")
        initCommands = ["taret list", "platform list"]
        preRunCommands = ["image list a.out", "image dump sections a.out"]
        postRunCommands = ["help trace", "help process trace"]
        stopCommands = ["frame variable", "bt"]
        exitCommands = ["expr 2+3", "expr 3+4"]
        terminateCommands = ["expr 4+2"]
        session = self.session
        launch_handle = session.initialize_and_launch(
            LaunchArgs(
                program,
                initCommands=initCommands,
                preRunCommands=preRunCommands,
                postRunCommands=postRunCommands,
                stopCommands=stopCommands,
                exitCommands=exitCommands,
                terminateCommands=terminateCommands,
            )
        )
        last_resp = session.last_response()
        session.wait_for_event(InitializedEvent, after=last_resp)

        # Get output from the console. This should contain both the
        # "initCommands" and the "preRunCommands".
        coutput = session.collect_console_until(postRunCommands[-1], after=last_resp)
        output = coutput.seen_texts
        # Verify all "initCommands" were found in console output
        session.verify_commands("initCommands", output, initCommands)
        # Verify all "preRunCommands" were found in console output
        session.verify_commands("preRunCommands", output, preRunCommands)
        # Verify all "postRunCommands" were found in console output
        session.verify_commands("postRunCommands", output, postRunCommands)

        source = "main.cpp"
        first_line = line_number(source, "// breakpoint 1")
        second_line = line_number(source, "// breakpoint 2")
        lines = [first_line, second_line]

        # Set 2 breakpoints so we can verify that "stopCommands" get run as the
        # breakpoints get hit
        breakpoint_ids = session.resolve_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )

        session.verify_configuration_done()
        launch_response = session.get_response(launch_handle)

        # Continue after launch and hit the first breakpoint.
        # Get output from the console. This should contain both the
        # "stopCommands" that were run after the first breakpoint was hit
        session.wait_until_any_breakpoint_hit(breakpoint_ids, after=last_resp)
        coutput = session.collect_console_until(stopCommands[-1], after=launch_response)
        output = coutput.seen_texts
        session.verify_commands("stopCommands", output, stopCommands)

        # Continue again and hit the second breakpoint.
        # Get output from the console. This should contain both the
        # "stopCommands" that were run after the second breakpoint was hit
        session.continue_to_any_breakpoint(breakpoint_ids)
        coutput = session.collect_console_until(
            pattern=stopCommands[-1], after=coutput.event
        )
        output = coutput.seen_texts
        session.verify_commands("stopCommands", output, stopCommands)

        # Continue until the program exits
        session.continue_to_exit()
        # Get output from the console. This should contain both the
        # "exitCommands" that were run after the second breakpoint was hit
        # and the "terminateCommands" due to the debugging session ending
        coutput = session.collect_console_until(
            pattern=terminateCommands[0], after=coutput.event
        )
        output = coutput.seen_texts
        session.verify_commands("exitCommands", output, exitCommands)
        session.verify_commands("terminateCommands", output, terminateCommands)

    TEST_PROGRAM = r"""
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <direct.h>
#else
#include <unistd.h>
#endif

int main(int argc, char const *argv[], char const *envp[]) {
  for (int i = 0; i < argc; ++i)
    printf("arg[%i] = \"%s\"\n", i, argv[i]);
  for (int i = 0; envp[i]; ++i)
    printf("env[%i] = \"%s\"\n", i, envp[i]);
  char *cwd = getcwd(NULL, 0);
  printf("cwd = \"%s\"\n", cwd); // breakpoint 1
  free(cwd);
  cwd = NULL;
  return 0; // breakpoint 2
}
"""
