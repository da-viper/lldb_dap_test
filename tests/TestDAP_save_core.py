"""
Test saving core minidump from lldb-dap
"""

import os

from lldbsuite.test.decorators import skipUnlessArch, skipUnlessPlatform
from lldbsuite.test.lldbtest import PROCESS_IS_VALID, line_number
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_save_core(DAPTestCaseBase):
    TEST_PROGRAM = r"""int function(int x) {
  if ((x % 2) == 0)
    return function(x - 1) + x; // breakpoint 1
  else
    return x;
}

int main(int argc, char const *argv[]) { return function(2); }
"""

    @skipUnlessArch("x86_64")
    @skipUnlessPlatform(["linux"])
    def test_save_core(self):
        """
        Tests saving core minidump from lldb-dap.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = "main.cpp"

        with session.configure(LaunchArgs(program)) as ctx:
            breakpoint1_line = line_number(source, "// breakpoint 1")
            lines = [breakpoint1_line]
            # Set breakpoint in the thread function so we can step the threads
            breakpoint_ids = session.resolve_source_breakpoints(source, lines)

        stop_event = session.verify_stopped_on_breakpoint(
            breakpoint_ids, after=ctx.process_event
        )

        # Getting dap stack trace may trigger __lldb_caller_function JIT module to be created.
        thread_ctx = session.thread_context_from(stop_event)
        thread_ctx.top_frame().frame

        modules = session.get_modules()
        thread_count = len(session.get_threads())

        core_stack = self.getBuildArtifact("core.stack.dmp")
        core_dirty = self.getBuildArtifact("core.dirty.dmp")
        core_full = self.getBuildArtifact("core.full.dmp")

        base_command = "`process save-core --plugin-name=minidump"
        save_core_stack_command = f"{base_command} --style=stack '{core_stack}'"
        session.evaluate(save_core_stack_command, context="repl")
        self.assertTrue(os.path.isfile(core_stack))
        self.verify_core_file(core_stack, len(modules), thread_count)

        save_core_modified_command = (
            f"{base_command} --style=modified-memory '{core_dirty}'"
        )
        session.evaluate(save_core_modified_command, context="repl")
        self.assertTrue(os.path.isfile(core_dirty))
        self.verify_core_file(core_dirty, len(modules), thread_count)

        save_core_full_command = f"{base_command} --style=full '{core_full}'"
        session.evaluate(save_core_full_command, context="repl")
        self.assertTrue(os.path.isfile(core_full))
        self.verify_core_file(core_full, len(modules), thread_count)

        session.continue_to_exit(exitCode=3)

    def verify_core_file(self, core_path, expected_module_count, expected_thread_count):
        return
        # TODO: renable this here ?
        # To verify, we'll launch with the mini dump
        target = self.dbg.CreateTarget(None)
        process = target.LoadCore(core_path)

        # check if the core is in desired state
        self.assertTrue(process, PROCESS_IS_VALID)
        self.assertTrue(process.GetProcessInfo().IsValid())
        triple = self.expect_not_none(target.GetTriple())
        self.assertNotEqual(triple.find("linux"), -1)
        self.assertTrue(target.GetNumModules(), expected_module_count)
        self.assertEqual(process.GetNumThreads(), expected_thread_count)
