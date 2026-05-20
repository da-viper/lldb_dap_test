from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import DAPError, DisconnectArgs, LaunchArgs, StoppedEvent


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
        process_event = session.launch_using_config(LaunchArgs(program=program))

        session.verify_process_exited(after=process_event)
        session.request_and_respond(DisconnectArgs())

    def test_launch_nonexistent_program(self):
        """Test launching a non-existent program"""
        session = self.build_and_create_session()
        launch_args = LaunchArgs(program="nonexistent/program")
        handle = session.initialize_and_launch(launch_args)

        with self.assertRaises(AssertionError):
            session.verify_configuration_done()

        error_response = session.get_error_response(handle)
        self.assertFalse(error_response.success, f"{error_response}")
        disconnect_response = session.request_and_respond(DisconnectArgs())
        self.assertTrue(disconnect_response.success, f"{disconnect_response}")

    def test_launch_with_stop_on_entry(self):
        """Test launching with stopOnEntry"""
        test_program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()

        process_event = session.launch_using_config(
            LaunchArgs(program=test_program, stopOnEntry=True)
        )

        session.verify_stopped_on_entry(after=process_event)
        session.continue_to_exit()
