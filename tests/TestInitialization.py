from unittest import expectedFailure
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import InitializeArgs, LaunchArgs


class TestInitialization(DAPTestCaseBase):
    """Test initialization and basic protocol"""

    TEST_PROGRAM = """
#include <iostream>
int main() { 
    std::cout << "[STDOUT]: from stdout\\n";
    std::cerr << "[STDERR]: from stderr\\n";
} 
"""

    def test_initialize_event(self):
        session = self.session
        self.session.initialize_sequence(self.session.initialize_args)
        session.disconnect()
        session.stop()
        with self.assertRaises(AssertionError):
            session.ensure_initialized()

    def test_initialize(self):
        capabilities = self.session.initialize_sequence(
            self.session.initialize_args
        ).body

        self.assertIsNotNone(capabilities)
        self.assertTrue(capabilities.supportsConfigurationDoneRequest)

    def test_default_initialize(self):
        capabilities = self.session.initialize_sequence(InitializeArgs()).body

        self.assertIsNotNone(capabilities)
        self.assertTrue(capabilities.supportsConfigurationDoneRequest)

    def test_initialize_with_custom_client_id(self):
        init_args = InitializeArgs(adapterID="python", clientID="custom-test-client")
        capabilities = self.session.initialize_sequence(init_args)

        self.assertIsNotNone(capabilities)

    @expectedFailure
    def test_initialize_with_missing_required_attribute(self):
        init_args = InitializeArgs(adapterID=None)
        capabilities = self.session.initialize_sequence(init_args)
        self.assertIsNotNone(capabilities)
