"""
Test lldb-dap disconnect request
"""


import os
import time

from lldbsuite.test import lldbutil
from lldbsuite.test.decorators import expectedFailureNetBSD, skipIfWindows
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import AttachArgs, LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestDAP_disconnect(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False

    TEST_PROGRAM = r"""
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

#include <chrono>
#include <cstdio>
#include <fstream>
#include <string>
#include <thread>

volatile bool wait_for_attach = true;

void handle_attach(char *sync_file_path) {
  lldb_enable_attach();

  {
    // Create a file to signal that this process has started up.
    std::ofstream sync_file;
    sync_file.open(sync_file_path);
  }

  while (wait_for_attach)
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
}

int main(int argc, char **args) {
  if (argc == 2)
    handle_attach(args[1]);

  // We let the binary live a little bit to see if it executed after detaching
  // from // breakpoint

  puts("hello world\n");
  // Create a file to signal that this process has started up.
  std::ofstream out_file; // breakpoint
  out_file.open(std::string(args[0]) + ".side_effect");
  return 0;
}
"""
    source = "main.cpp"

    def disconnect_and_assert_no_output_printed(self):
        session = self.create_session()
        session.disconnect()
        # verify we didn't get any input after disconnect
        time.sleep(2)
        output = session.get_stdout()
        self.assertTrue(output is None or len(output) == 0)

    @skipIfWindows
    def test_launch(self):
        """
        This test launches a process that would creates a file, but we disconnect
        before the file is created, which terminates the process and thus the file is not
        created.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session(disconnect_automatically=False)
        with session.configure(LaunchArgs(program, stopOnEntry=True)) as ctx:
            # We set a breakpoint right before the side effect file is created
            session.resolve_source_breakpoints(
                self.source, [line_number(self.source, "// breakpoint")]
            )
        session.verify_stopped_on_entry(after=ctx.process_event)

        # verify we haven't produced the side effect file yet
        self.assertFalse(os.path.exists(program + ".side_effect"))

        session.disconnect()

        # verify we didn't produce the side effect file
        time.sleep(1)
        self.assertFalse(os.path.exists(program + ".side_effect"))

    @skipIfWindows
    @expectedFailureNetBSD
    def test_attach(self):
        """
        This test attaches to a process that creates a file. We attach and disconnect
        before the file is created, and as the process is not terminated upon disconnection,
        the file is created anyway.
        """
        session = self.build_and_create_session(disconnect_automatically=False)
        program = self.getBuildArtifact("a.out")

        # Use a file as a synchronization point between test and inferior.
        sync_file_path = lldbutil.append_to_process_working_directory(
            self, f"sync_file_{time.time()}"
        )
        self.addTearDownHook(lambda: self.run_platform_command(f"rm {sync_file_path}"))

        proc = self.spawnSubprocess(program, [sync_file_path])
        lldbutil.wait_for_file_on_target(self, sync_file_path)

        attach_args = AttachArgs(pid=proc.pid, stopOnEntry=True)
        process_event = session.attach(attach_args)
        stop_event = session.verify_stopped_on_entry(after=process_event)

        thread_ctx = session.thread_context_from(stop_event)
        thread_ctx.top_frame().evaluate("wait_for_attach = false;")

        # verify we haven't produced the side effect file yet
        self.assertFalse(os.path.exists(program + ".side_effect"))

        session.disconnect()
        time.sleep(2)
        # verify we produced the side effect file, as the program continued after disconnecting
        self.assertTrue(os.path.exists(program + ".side_effect"))
