"""
Test lldb-dap command hooks
"""


from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import AttachArgs, LaunchArgs


class TestDAP_commands(DAPTestCaseBase):
    SHARED_BUILD_TESTCASE = False

    TEST_PROGRAM = r"""
    int main() { return 0; }
"""

    def test_command_directive_quiet_on_success(self):
        program = self.getBuildArtifact("a.out")
        command_quiet = (
            "settings set target.show-hex-variable-values-with-leading-zeroes false"
        )
        command_not_quiet = (
            "settings set target.show-hex-variable-values-with-leading-zeroes true"
        )
        session = self.build_and_create_session()
        process_event = session.launch_using_config(
            LaunchArgs(
                program,
                initCommands=["?" + command_quiet, command_not_quiet],
                terminateCommands=["?" + command_quiet, command_not_quiet],
                stopCommands=["?" + command_quiet, command_not_quiet],
                exitCommands=["?" + command_quiet, command_not_quiet],
            )
        )
        session.verify_process_exited(after=process_event)
        full_output = session.get_console()
        self.assertNotIn(command_quiet, full_output)
        self.assertIn(command_not_quiet, full_output)

    def do_test_abort_on_error(
        self,
        use_init_commands: bool = False,
        use_launch_commands: bool = False,
        use_pre_run_commands: bool = False,
        use_post_run_commands: bool = False,
    ):
        program = self.create_test_program_with_name("main.cpp")
        command_quiet = (
            "settings set target.show-hex-variable-values-with-leading-zeroes false"
        )
        command_abort_on_error = "settings set foo bar"
        commands: list[str] = ["?!" + command_quiet, "!" + command_abort_on_error]

        session = self.build_and_create_session()
        session.initialize_and_launch(
            LaunchArgs(
                program,
                initCommands=commands if use_init_commands else None,
                launchCommands=commands if use_launch_commands else None,
                preRunCommands=commands if use_pre_run_commands else None,
                postRunCommands=commands if use_post_run_commands else None,
            )
        )
        session.verify_configuration_done(use_post_run_commands)
        full_output = session.get_console()
        self.assertNotIn(command_quiet, full_output)
        self.assertIn(command_abort_on_error, full_output)

    def test_command_directive_abort_on_error_init_commands(self):
        self.do_test_abort_on_error(use_init_commands=True)

    def test_command_directive_abort_on_error_launch_commands(self):
        self.do_test_abort_on_error(use_launch_commands=True)

    def test_command_directive_abort_on_error_pre_run_commands(self):
        self.do_test_abort_on_error(use_pre_run_commands=True)

    def test_command_directive_abort_on_error_post_run_commands(self):
        self.do_test_abort_on_error(use_post_run_commands=True)

    def test_command_directive_abort_on_error_attach_commands(self):
        program = self.create_test_program_with_name("main.cpp")
        command_quiet = (
            "settings set target.show-hex-variable-values-with-leading-zeroes false"
        )
        command_abort_on_error = "settings set foo bar"
        session = self.build_and_create_session()
        session.initialize_sequence(session.initialize_args)
        with self.assertRaises(AssertionError):
            session.attach_and_configuration_done(
                AttachArgs(
                    program=program,
                    attachCommands=["?!" + command_quiet, "!" + command_abort_on_error],
                )
            )
        full_output = session.get_console()
        self.assertNotIn(command_quiet, full_output)
        self.assertIn(command_abort_on_error, full_output)
