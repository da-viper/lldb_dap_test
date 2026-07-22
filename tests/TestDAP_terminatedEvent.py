"""
Test lldb-dap terminated event
"""

import json
import shutil
import sys

from lldbsuite.test.decorators import (
    skipIfTargetDoesNotSupportSharedLibraries,
    skipIfWindows,
)
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


@skipIfTargetDoesNotSupportSharedLibraries()
class TestDAP_terminatedEvent(DAPTestCaseBase):
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

    @skipIfWindows
    def test_terminated_event(self):
        """
        Terminated Event
        Now contains the statistics of a debug session:
        metatdata:
            totalDebugInfoByteSize > 0
            totalDebugInfoEnabled > 0
            totalModuleCountHasDebugInfo > 0
            ...
        targetInfo:
            totalBreakpointResolveTime > 0
        breakpoints:
            recognize function breakpoint
            recognize source line breakpoint
        It should contain the breakpoints info: function bp & source line bp
        """
        program = self.getBuildArtifact("a.out.stripped")
        session = self.build_and_create_session()
        source = self.getSourcePath("main.cpp")
        main_bp_line = line_number(source, "// main breakpoint 1")

        with session.configure(LaunchArgs(program=program)) as ctx:
            # This breakpoint will be resolved only when the libfoo module is loaded.
            func_response = session.set_function_breakpoints(["foo"])
            breakpoints = func_response.body.breakpoints
            breakpoints.extend(
                session.set_source_breakpoints(source, [main_bp_line]).body.breakpoints
            )
        breakpoint_ids = [bp.id for bp in breakpoints if bp.id is not None]
        self.assertEqual(len(breakpoint_ids), 2, "expect one breakpoint")
        last_bp_event = session.wait_until_any_breakpoint_hit(
            breakpoint_ids, after=ctx.process_event
        )
        session.continue_to_exit()

        terminated = session.wait_for_terminated_event(after=last_bp_event)
        body = self.expect_not_none(terminated.body)
        statistics = body.lldb_statistics

        self.assertGreater(statistics["totalDebugInfoByteSize"], 0)
        self.assertGreater(statistics["totalDebugInfoEnabled"], 0)
        self.assertGreater(statistics["totalModuleCountHasDebugInfo"], 0)

        self.assertIsNotNone(statistics["memory"])
        self.assertNotIn("modules", statistics.keys())

        # lldb-dap debugs one target at a time.
        target = json.loads(statistics["targets"])[0]
        self.assertGreater(target["totalBreakpointResolveTime"], 0)

        breakpoints = target["breakpoints"]
        self.assertIn(
            "foo",
            breakpoints[0]["details"]["Breakpoint"]["BKPTResolver"]["Options"][
                "SymbolNames"
            ],
            "foo is a symbol breakpoint",
        )
        self.assertTrue(
            breakpoints[1]["details"]["Breakpoint"]["BKPTResolver"]["Options"][
                "FileName"
            ].endswith("main.cpp"),
            "target has source line breakpoint in main.cpp",
        )
