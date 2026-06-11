"""
Test lldb-dap launch request.
"""

from lldbsuite.test.tools.lldb_dap.dap_types import (
    ExitedEvent,
    LaunchArgs,
    StoppedEvent,
)
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_launch_stopOnEntry(DAPTestCaseBase):
    """
    Tests the default launch of a simple program that stops at the
    entry point instead of continuing.
    """

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
}"""
    IS_C = True

    def test(self):
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program, stopOnEntry=True))
        stop_event = session.verify_stopped_on_entry(after=process_event)
        exit_event = session.continue_to_exit()

        # Verify we did not receive any other stop event.
        new_stop_events = []

        def matches_exit_event(evt):
            # Collect stopped events until exit event.
            if isinstance(evt, StoppedEvent):
                new_stop_events.append(evt)
            return evt == exit_event

        session.wait_for_any_event(
            (StoppedEvent, ExitedEvent), after=stop_event, until=matches_exit_event
        )
        fail_msg = (f"expected no new stopped events. events: {new_stop_events}",)
        self.assertEqual(len(new_stop_events), 0, fail_msg)
