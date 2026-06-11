"""
Test lldb-dap terminated event
"""

import json
import shutil
import sys

from lldbsuite.test.decorators import (
    skipIfRemote,
    skipIfTargetDoesNotSupportSharedLibraries,
    skipIfWindows,
)
from lldbsuite.test.tools.lldb_dap import lldb_dap_testcase
from lldbsuite.test.tools.lldb_dap.dap_types import InitializedEvent, LaunchArgs


@skipIfTargetDoesNotSupportSharedLibraries()
class TestDAP_eventStatistic(lldb_dap_testcase.DAPTestCaseBase):
    """

    Test case that captures both initialized and terminated events.

    META-ONLY: Intended to succeed TestDAP_terminatedEvent.py, but upstream keeps updating that file, so both that and this file will probably exist for a while.

    """

    MAIN_CPP = r"""#include "foo.h"
#include <iostream>

int main(int argc, char const *argv[]) {
  std::cout << "Hello World!" << std::endl; // main breakpoint 1
  foo();
  return 0;
}
"""
    FOO_H = r"""int foo();
"""
    FOO_CPP = r"""int foo() { return 12; }
"""

    def build(self, filename=None):
        main_path = self.create_file(self.MAIN_CPP, "main.cpp")
        foo_path = self.create_file(self.FOO_CPP, "foo.cpp")
        self.create_file(self.FOO_H, "foo.h")

        shared_lib_name = "libfoo.so" if sys.platform == "linux" else "libfoo.dylib"
        # Build the shared library that defines foo().
        self.run_command(
            [
                "/usr/bin/clang++",
                "-fPIC",
                "-g",
                "-shared",
                foo_path,
                "-o",
                self.getBuildArtifact(shared_lib_name),
            ]
        )
        # Build main, linked against libfoo with an rpath into the build dir.
        self.run_command(
            [
                "/usr/bin/clang++",
                "-g",
                main_path,
                f"-Wl,-rpath,{self.test_dir}",
                f"-L{self.test_dir}",
                "-lfoo",
                "-o",
                self.getBuildArtifact("a.out"),
            ]
        )
        # Strip into a.out.stripped — the test launches the stripped binary
        # so symbols come exclusively from debug info / shlib resolution.
        self.run_command(
            [
                "/usr/bin/strip",
                "-o",
                self.getBuildArtifact("a.out.stripped"),
                self.getBuildArtifact("a.out"),
            ]
        )
        if codesign := shutil.which("codesign"):
            self.run_command(
                [codesign, "-fs", "-", self.getBuildArtifact("a.out.stripped")]
            )

    def check_statistics_summary(self, statistics):
        self.assertTrue(statistics["totalDebugInfoByteSize"] > 0)
        self.assertTrue(statistics["totalDebugInfoEnabled"] > 0)
        self.assertTrue(statistics["totalModuleCountHasDebugInfo"] > 0)

        self.assertNotIn("modules", statistics.keys())

    def check_target_summary(self, statistics):
        # lldb-dap debugs one target at a time.
        target = json.loads(statistics["targets"])[0]
        self.assertIn("totalSharedLibraryEventHitCount", target)

    @skipIfWindows
    @skipIfRemote
    def test_terminated_event(self):
        """
        Terminated Event
        Now contains the statistics of a debug session:
        metadata:
            totalDebugInfoByteSize > 0
            totalDebugInfoEnabled > 0
            totalModuleCountHasDebugInfo > 0
            ...
        """

        program_basename = "a.out.stripped"
        program = self.getBuildArtifact(program_basename)
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program))
        session.verify_process_exited()

        terminated_event = session.wait_for_terminated(after=process_event)
        terminated_body = self.expect_not_none(terminated_event.body)
        statistics = terminated_body.lldb_statistics
        self.check_statistics_summary(statistics)
        self.check_target_summary(statistics)

    @skipIfWindows
    @skipIfRemote
    def test_initialized_event(self):
        """
        Initialized Event
        Now contains the statistics of a debug session:
            totalDebugInfoByteSize > 0
            totalDebugInfoEnabled > 0
            totalModuleCountHasDebugInfo > 0
            ...
        """

        program_basename = "a.out"
        program = self.getBuildArtifact(program_basename)
        session = self.build_and_create_session()
        pending_launch = session.initialize_and_launch(LaunchArgs(program))

        init_event = session.wait_for_earliest_event(InitializedEvent)
        init_body = self.expect_not_none(init_event.body)
        statistics = init_body.lldb_statistics
        self.check_statistics_summary(statistics)

        session.verify_configuration_done()
        launch_response = pending_launch.result()
        session.verify_process_exited(after=launch_response)
