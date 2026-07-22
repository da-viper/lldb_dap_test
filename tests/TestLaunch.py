from lldbsuite.test.tools.lldb_dap.types import (
    DisconnectArgs,
    LaunchArgs,
)
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


class TestLaunchAndTerminate(DAPTestCaseBase):
    """Test launch and terminate operations"""

    TEST_PROGRAM = """
#include <iostream>
int main() { 
    std::cout << "[STDOUT]: from stdout\\n";
    std::cerr << "[STDERR]: from stderr\\n";
} 
"""

    def test_launch_simple_program(self):
        """Test launching a simple program"""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program=program))

        session.verify_process_exited(after=process_event)

    def test_launch_nonexistent_program(self):
        """Test launching a non-existent program"""
        session = self.build_and_create_session()
        launch_args = LaunchArgs(program="nonexistent/program")
        handle = session.initialize_and_launch(launch_args)

        session.verify_configuration_done(expected_success=False)

        error_response = handle.error()
        self.assertFalse(error_response.success, f"{error_response}")

    def test_launch_with_stop_on_entry(self):
        """Test launching with stopOnEntry"""
        test_program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()

        process_event = session.launch(
            LaunchArgs(program=test_program, stopOnEntry=True)
        )

        session.verify_stopped_on_entry(after=process_event)
        session.continue_to_exit()
