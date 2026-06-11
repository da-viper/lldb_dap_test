"""
Test lldb-dap module request
"""

import platform
import re
import shutil
import sys

from lldbsuite.test.decorators import skipIfWindows, skipUnlessDarwin
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.dap_types import (
    CompileUnitsArgs,
    LaunchArgs,
    ModuleEvent,
    ModuleReason,
)
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_module(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include "foo.h"

int main(int argc, char const *argv[]) {
  foo();
  return 0; // breakpoint 1
}
"""
    FOO_CPP = r"""int foo() { return 12; } """
    FOO_H = r"""int foo(); """

    def build(self):
        program_path = self.create_file(self.TEST_PROGRAM, "main.cpp")
        foo_path = self.create_file(self.FOO_CPP, "foo.cpp")
        self.create_file(self.FOO_H, "foo.h")

        # create the dylib
        shared_lib_name = "libfoo.so" if sys.platform == "linux" else "libfoo.dylib"
        self.run_command(
            [
                "/usr/bin/clang",
                "-fPIC",
                "-g",
                "-shared",
                foo_path,
                "-o",
                self.getBuildArtifact(shared_lib_name),
            ]
        )
        self.run_command(
            [
                "/usr/bin/clang++",
                "-fPIC",
                "-g",
                program_path,
                f"-Wl,-rpath,{self.test_dir}",
                f"-L{self.test_dir}",
                "-ldl",
                f"-lfoo",
                "-o",
                self.getBuildArtifact("a.out"),
            ]
        )
        # strip binaries
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

    def run_test(self, symbol_basename: str, expect_debug_info_size: bool):
        session = self.build_and_create_session()
        program_basename = "a.out.stripped"
        program = self.getBuildArtifact(program_basename)

        with session.configure(LaunchArgs(program)) as ctx:
            # This breakpoint will be resolved only when the libfoo module is loaded.
            breakpoints = session.set_function_breakpoints(["foo"]).body.breakpoints
            self.assertEqual(len(breakpoints), 1, "expect one breakpoint.")

            foo_bp_id = self.expect_not_none(breakpoints[0].id)

        session.verify_stopped_on_breakpoint(foo_bp_id, after=ctx.process_event)
        active_modules = session.get_modules()
        program_module = active_modules[program_basename]
        self.assertIn(
            program_basename,
            active_modules,
            f"{program_basename} module is in active modules",
        )
        self.assertEqual(program_basename, program_module.name)
        self.assertIsNotNone(program_module.path, "make sure path is in module")
        self.assertEqual(program, program_module.path)
        self.assertIsNone(
            program_module.symbolFilePath, "Make sure a.out.stripped has no debug info"
        )
        symbols_path = self.getBuildArtifact(symbol_basename)
        modules_response = session.last_response()
        session.evaluate(
            f'''`target symbols add -s "{program}" "{symbols_path}"''', context="repl"
        )

        # Make sure we got an update event for the program module when the
        # symbols got added.
        changed_event = session.verify_next_module_event(
            ModuleReason.CHANGED, after=modules_response
        )
        changed_module = changed_event.body.module
        self.assertEqual(program_module.name, changed_module.name)
        self.assertIsNotNone(changed_module.symbolFilePath)
        changed_symbols_path = self.expect_not_none(changed_module.symbolFilePath)
        self.assertIn(symbols_path, changed_symbols_path)

        if expect_debug_info_size:
            changed_debug_size = self.expect_not_none(changed_module.debugInfoSize)
            size_regex = re.compile(r"[0-9]+(\.[0-9]*)?[KMG]?B")
            self.assertRegex(
                changed_debug_size, size_regex, "expect has debug info size"
            )

        active_modules = session.get_modules()
        program_module = active_modules[program_basename]
        self.assertEqual(program_basename, program_module.name)
        self.assertEqual(program, program_module.path)
        self.assertIsNotNone(program_module.addressRange)

        # Collect all the module names we saw as events.
        module_new_names = []

        def seen_program_changed_event(event: ModuleEvent):
            if event.body.reason == ModuleReason.NEW:
                module_new_names.append(event.body.module.name)

            is_changed_event = event.seq == changed_event.seq
            return is_changed_event

        session.wait_for_module_event(
            after=ctx.init_response, until=seen_program_changed_event
        )
        # Make sure we got an event for every active module.
        self.assertNotEqual(len(module_new_names), 0)
        for module in active_modules:
            self.assertIn(module, module_new_names)

        session.continue_to_exit()

    @skipIfWindows
    def test_modules(self):
        """
        Mac or linux.

        On mac, if we load a.out as our symbol file, we will use DWARF with .o files and we will
        have debug symbols, but we won't see any debug info size because all of the DWARF
        sections are in .o files.

        On other platforms, we expect a.out to have debug info, so we will expect a size.
        """
        return self.run_test(
            "a.out", expect_debug_info_size=platform.system() != "Darwin"
        )

    @skipUnlessDarwin
    def test_modules_dsym(self):
        """
        Darwin only test with dSYM file.

        On mac, if we load a.out.dSYM as our symbol file, we will have debug symbols and we
        will have DWARF sections added to the module, so we will expect a size.
        """
        return self.run_test("a.out.dSYM", expect_debug_info_size=True)

    @skipIfWindows
    def test_compile_units(self):
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        source = "main.cpp"
        main_source_path = self.getSourcePath(source)
        with session.configure(LaunchArgs(program)) as ctx:
            breakpoint1_line = line_number(source, "// breakpoint 1")
            bp_ids = session.resolve_source_breakpoints(source, [breakpoint1_line])
        process_event = ctx.process_event

        session.verify_stopped_on_breakpoint(bp_ids, after=process_event)

        module_id = session.get_modules()["a.out"].id
        response = session.send_request(CompileUnitsArgs(module_id)).result()
        cu_paths = [cu.compileUnitPath for cu in response.body.compileUnits]
        self.assertIn(main_source_path, cu_paths, "Real path to main.cpp matches")

        session.continue_to_exit()
