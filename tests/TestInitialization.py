from unittest import expectedFailure

from lldb_dap.dap_types import InitializeArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase


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
        session = self.create_session()
        session.initialize_sequence(session.initialize_args)
        session.do_disconnect()
        session.stop()
        self.assertFalse(session.is_running())
        with self.assertRaises(AssertionError):
            session.ensure_initialized()

    def test_initialize(self):
        session = self.create_session()
        capabilities = session.initialize_sequence(session.initialize_args).body

        self.assertIsNotNone(capabilities)
        self.assertTrue(capabilities.supportsConfigurationDoneRequest)

    def test_default_initialize(self):
        session = self.create_session()
        capabilities = session.initialize_sequence(InitializeArgs()).body

        self.assertIsNotNone(capabilities)
        self.assertTrue(capabilities.supportsConfigurationDoneRequest)

    def test_initialize_with_custom_client_id(self):
        session = self.build_and_create_session()
        init_args = InitializeArgs(adapterID="python", clientID="custom-test-client")
        capabilities = session.initialize_sequence(init_args)

        self.assertIsNotNone(capabilities)

    @expectedFailure
    def test_initialize_with_missing_required_attribute(self):
        session = self.build_and_create_session()
        init_args = InitializeArgs(adapterID=None)
        capabilities = session.initialize_sequence(init_args)
        self.assertIsNotNone(capabilities)
