"""
Test lldb-dap stepInTargets request
"""

from lldb_dap.lldb_dap_testcase import skipif_linux
import unittest
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number, skipif_darwin
from lldb_dap.dap_types import LaunchArgs, StepInTargetsArgs


# @unittest.skip("")
class TestDAP_stepInTargets(DAPTestCaseBase):
    TEST_PROGRAM = r"""
int foo(int val, int extra) { return val + extra; }

int funcA() { return 22; }

int funcB() { return 54; }

int main(int argc, char const *argv[]) {
  foo(funcA(), funcB()); // set breakpoint here
  return 0;
}

"""

    # @expectedFailureAll(oslist=["windows"]) #TODO enable this later
    # @skipIf(archs=no_match(["x86_64"])) #TODO enable this later
    # InstructionControlFlowKind for ARM is not supported yet.
    # On Windows, lldb-dap seems to ignore targetId when stepping into functions.
    # For more context, see https://github.com/llvm/llvm-project/issues/98509.
    @skipif_darwin()
    def test_basic(self):
        """
        Tests the basic stepping in targets with directly calls.
        """
        program = self.create_test_program_with_name(
            "main.cpp"
        )  # self.getBuildArtifact("a.out")
        source = self.getSourcePath("main.cpp")

        breakpoint_line = line_number(source, "// set breakpoint here")
        lines = [breakpoint_line]
        session = self.session
        # Set breakpoint in the thread function so we can step the threads
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, lines)
        process_event = ctx.process_event()
        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        thread_ctxs = session.get_thread_context(stop_event.body.threadId)
        top_frame = thread_ctxs.top_frame()

        # Request all step in targets list and verify the response.
        step_in_targets_response = session.request_and_respond(
            StepInTargetsArgs(top_frame.frame.id)
        )
        self.assertEqual(step_in_targets_response.success, True, "expect success")
        step_in_targets = step_in_targets_response.body.targets

        self.assertEqual(len(step_in_targets), 3, "expect 3 step in targets")

        # Verify the target names are correct.
        # The order of funcA and funcB may change depending on the compiler ABI.
        funcA_target = None
        funcB_target = None
        for target in step_in_targets[0:2]:
            if "funcB" in target.label:
                funcB_target = target
            elif "funcA" in target.label:
                funcA_target = target
            else:
                self.fail(f"Unexpected step in target: {target}")

        self.assertIsNotNone(funcA_target, "expect funcA")
        self.assertIsNotNone(funcB_target, "expect funcB")
        self.assertIn("foo", step_in_targets[2].label, "expect foo")

        # Choose to step into second target and verify that we are in the second target,
        # be it funcA or funcB.
        thread_ctxs.step_in(targetId=step_in_targets[1].id)
        top_frame = thread_ctxs.top_frame().frame
        self.assertIsNotNone(top_frame, "expect a leaf frame")
        self.assertEqual(step_in_targets[1].label, top_frame.name)

        session.continue_to_exit()

    # @skipIf(archs=no_match(["x86", "x86_64"])) # TODO: enable later.
    @skipif_darwin()
    def test_supported_capability_x86_arch(self):
        program = self.create_test_program_with_name("main.cpp")
        source = self.getSourcePath("main.cpp")
        session = self.session
        bp_lines = [line_number(source, "// set breakpoint here")]
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, bp_lines)
        process_event = ctx.process_event()

        session.verify_stopped_on_breakpoint(after=process_event)
        self.assertTrue(
            session.capabilities().supportsStepInTargetsRequest,
            f"expect capability `stepInTarget` is supported with architecture {self.getArchitecture()}",
        )
        session.continue_to_exit()

    # @skipIf(archs=["x86", "x86_64"]) # TODO: enable later
    @skipif_linux()
    def test_supported_capability_other_archs(self):
        program = self.create_test_program_with_name("main.cpp")
        source = self.getSourcePath("main.cpp")
        session = self.session
        bp_lines = [line_number(source, "// set breakpoint here")]
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, bp_lines)
        process_event = ctx.process_event()

        session.verify_stopped_on_breakpoint(after=process_event)
        self.assertFalse(
            session.capabilities().supportsStepInTargetsRequest,
            f"expect capability `stepInTarget` is not supported with architecture {self.getArchitecture()}",
        )
        session.continue_to_exit()
