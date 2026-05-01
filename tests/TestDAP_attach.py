"""
Test lldb-dap attach request
"""

import os
import sys
import time
from typing import List, Optional
import unittest
import uuid
import subprocess

from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import AttachArgs


def wait_for_file_on_target(testcase: unittest.TestCase, file_path):
    import time

    MAX_ATTEMPTS = 5
    timeout_seconds = 4 if "ASAN_OPTIONS" in os.environ else 1
    for _ in range(MAX_ATTEMPTS):
        command = ["/usr/bin/ls", file_path]
        res = subprocess.run(command)
        err, retcode, msg = res.stderr, res.returncode, res.stdout
        if not err and retcode == 0:
            break

        time.sleep(timeout_seconds)
    else:
        testcase.fail(
            "File %s not found even after %d attempts." % (file_path, MAX_ATTEMPTS)
        )


# Often fails on Arm Linux, but not specifically because it's Arm, something in
# process scheduling can cause a massive (minutes) delay during this test.
# @skipIf(oslist=["linux"], archs=["arm$"])
@unittest.skip("NOT IMPLEMENTED")
class TestDAP_attach(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False
    TEST_PROGRAM = r"""
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

#include <stdio.h>
#ifdef _WIN32
#include <process.h>
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

  // Wait on input from stdin.
  getchar();

  printf("pid = %i\n", getpid());
  return 0;
}
"""

    def spawn(self, program: str, args: Optional[List[str]] = None):
        process_args = [program]
        process_args.extend(args or [])
        return subprocess.Popen(
            process_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

    def verify_pid(self, proc: subprocess.Popen):
        self.assertIsNone(proc.poll())
        out, _ = proc.communicate("foo")

        self.assertIn(f"pid = {proc.pid}", out)

    def build_program_for_attach(self):
        unique_name = str(uuid.uuid4())
        filename = self.create_file(self.TEST_PROGRAM, "main.c")
        program = self.compile_program(filename, unique_name)
        return program

    def test_by_pid(self):
        """Tests attaching to a process by process ID."""
        # TODO: change this.
        program = self.build_program_for_attach()

        proc = self.spawn(program=program)
        self.assertIsNone(proc.poll())

        process_event, _ = self.session.attach_using_config(AttachArgs(pid=proc.pid))
        self.assertIsNone(proc.poll())
        self.assertEqual(process_event.body.systemProcessId, proc.pid)
        self.verify_pid(proc)

    def test_by_name(self):
        """Tests attaching to a process by process name."""
        program = self.build_program_for_attach()

        # Use a file as a synchronization point between test and inferior.
        pid_file_path = self.create_file("", f"pid_file_{int(time.monotonic())}")

        proc = self.spawn(program=program, args=[pid_file_path])
        self.assertIsNone(proc.poll())
        wait_for_file_on_target(self, pid_file_path)
        wait_for_file_on_target(self, program)

        time.sleep(10)
        process_event, _ = self.session.attach_using_config(AttachArgs(program=program))
        self.assertIsNone(proc.poll())
        self.assertEqual(process_event.body.systemProcessId, proc.pid)
        self.verify_pid(proc)
