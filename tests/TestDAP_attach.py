"""
Test lldb-dap attach request
"""

import subprocess
import uuid
from pathlib import Path

from lldbsuite.test import lldbutil
from lldbsuite.test.decorators import (
    expectedFailureWindows,
    expectedFailureWindowsAndNoLLDBServer,
    skipIf,
    skipIfWasm,
    skipIfWindowsAndLLDBServer,
)
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase
from lldbsuite.test.tools.lldb_dap.types import (
    AttachArgs,
    ProcessEvent,
    ProgressStartEvent,
)


# Often fails on Arm Linux, but not specifically because it's Arm, something in
# process scheduling can cause a massive (minutes) delay during this test.
@skipIf(oslist=["linux"], archs=["arm$"])
@skipIfWasm
class TestDAP_attach(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False

    # TODO: this is different from the one that already exists
    TEST_PROGRAM = r"""
#include "attach.h"
#include <stdio.h>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

int main(int argc, char const *argv[]) {
  lldb_enable_attach();

  // Create the synchronization token.
  if (argc >= 2) {
    FILE *f = fopen(argv[1], "wx");
    if (!f)
        return 1;
    fputs("\n", f);
    fflush(f);
    fclose(f);

    // Wait on input from stdin. A debugger attach on macOS can interrupt
    // getchar() and set the stream's error indicator (EINTR). ignore that and
    // keep waiting until we actually receive a character.
    while (1) {
      int c = getchar();
      if (c == EOF && ferror(stdin)) {
        clearerr(stdin);
        continue;
      }
      printf("char = %c\n", c);
      break;
    }
  }

  printf("pid = %i\n", getpid());
  return 0; // breakpoint 1
}
"""
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

    def build(self, dictionary=None):
        self.create_file(self.ATTACH_H, "attach.h")
        super().build(dictionary)

    def spawn(self, program: str, *, wait_for_sync: bool = True):
        """Spawn the target and (by default) block until it has called `lldb_enable_attach`."""
        sync_token = lldbutil.append_to_process_working_directory(
            self, f"sync_{uuid.uuid4().hex}"
        )
        proc = self.spawnSubprocess(
            executable=program,
            args=[sync_token],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if wait_for_sync:
            lldbutil.wait_for_file_on_target(self, sync_token)

        self.subprocesses.append(proc)
        return proc

    def verify_pid(self, proc):
        out, _ = proc.communicate("f")

        self.assertIn(f"char = f", out)
        self.assertIn(f"pid = {proc.pid}", out)

    def test_by_pid(self):
        """Tests attaching to a process by process ID."""
        program = self.build_for_attach()
        session = self.create_session()

        proc = self.spawn(program=program)
        self.assertIsNone(proc.poll(), "process should be running")

        process_event = session.attach(AttachArgs(pid=proc.pid))
        self.assertEqual(process_event.body.systemProcessId, proc.pid)
        self.verify_pid(proc)

    def test_by_name(self):
        """Tests attaching to a process by process name."""
        program = self.build_for_attach()
        session = self.create_session()

        proc = self.spawn(program=program)

        process_event = session.attach(AttachArgs(program=program))
        self.assertEqual(process_event.body.systemProcessId, proc.pid)
        self.verify_pid(proc)

    @expectedFailureWindowsAndNoLLDBServer()
    def test_by_name_waitFor(self):
        """
        Tests waiting for, and attaching to a process by process name that
        doesn't exist yet.
        """
        self.do_attach_waitFor(use_basename=False)

    @expectedFailureWindows
    @skipIfWindowsAndLLDBServer
    def test_by_basename_waitFor(self):
        """
        Tests waiting for and attaching to a process by the process base name
        that doesn't exist yet.
        """
        self.do_attach_waitFor(use_basename=True)

    def do_attach_waitFor(self, use_basename: bool):
        """Kick off attach with waitFor=True; spawn the target once lldb-dap
        signals it has entered the wait-for-process polling loop."""
        session = self.create_session()
        program = self.build_for_attach()
        attach_name = Path(program).name if use_basename else program

        init_response = session.initialize_sequence(session.initialize_args)
        pending = session.send_request(AttachArgs(program=attach_name, waitFor=True))

        # Wait until lldb-dap is actually polling for the process before we
        # spawn it, so we don't race the poll setup.
        session.wait_for_event(
            ProgressStartEvent,
            until=lambda e: "Waiting to attach" in e.body.title,
            after=init_response,
            timeout_msg="Waiting for attach progress event.",
        )

        proc = self.spawn(program=program, wait_for_sync=False)

        session.ensure_initialized()
        session.verify_configuration_done()

        process_event = session.wait_for_event(ProcessEvent, after=init_response)
        pending.result("expects attach response.")

        self.assertEqual(process_event.body.systemProcessId, proc.pid)
        self.verify_pid(proc)

    def test_attach_with_missing_session_debugger(self):
        """
        Test that attaching with only one of debuggerId/targetId specified
        fails with the expected error message.
        """
        session = self.create_session()

        # Test with only targetId specified (no debuggerId)
        resp = session.initialize_and_launch(
            AttachArgs(session=AttachArgs.Session(targetId=99999))
        ).error()

        message = self.expect_not_none(resp.body and resp.body.error)
        self.assertIn(
            "missing value at arguments.session.debuggerId",
            message.format,
        )

    def test_attach_with_invalid_session(self):
        """
        Test that attaching with both debuggerId and targetId specified but
        invalid fails with an appropriate error message.
        """
        session = self.create_session()

        # Attach with both debuggerId=9999 and targetId=9999 (both invalid).
        # Since debugger ID 9999 likely doesn't exist in the global registry,
        # we expect a validation error.
        pending = session.initialize_and_launch(
            AttachArgs(session=AttachArgs.Session(targetId=9999, debuggerId=9999))
        )
        session.configuration_done().result_or_error()

        resp = pending.error()
        message = self.expect_not_none(resp.body and resp.body.error)
        error_msg = message.format
        # Either error is acceptable - both indicate the debugger reuse
        # validation is working correctly
        self.assertTrue(
            "Unable to find existing debugger" in error_msg
            or f"Expected debugger/target not found error, got: {error_msg}"
        )
