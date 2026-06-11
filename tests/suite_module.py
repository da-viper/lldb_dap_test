#!/usr/bin/env python3

import unittest
import time
from pathlib import Path
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from tests.TestDAPUtils_Types import TestDAPUtils_Types

# from tests.TestDAP_attach import TestDAP_attach
from tests.TestDAP_launch_cwd import TestDAP_launch_cwd
from tests.TestDAP_launch_disableSTDIO import TestDAP_launch_disableSTDIO
from tests.TestDAP_launch_termination import TestDAP_launch_termination
from tests.TestDAP_runInTerminal import TestDAP_runInTerminal
from tests.TestDAP_sendEvent import TestDAP_sendEvent
from tests.TestDAP_variables_children import TestDAP_variables_children
from tests.TestError import TestErrorHandling
from tests.TestInitialization import TestInitialization
from tests.TestLaunch import TestLaunchAndTerminate
from tests.TestDAP_launch_args import TestDAP_launch_args
from tests.TestDAP_launch_basic import TestDAP_launch_basic


# Test suite runner
def suite():
    """Create test suite"""
    test_suite = unittest.TestSuite()

    loader = unittest.TestLoader()
    # Add all test classes
    test_suite.addTests(loader.loadTestsFromTestCase(TestInitialization))

    # test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestDAP_launch_version))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestLaunchAndTerminate))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_launch_args))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_launch_basic))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_launch_cwd))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_launch_disableSTDIO))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_sendEvent))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAPTypes))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_variables_children))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_runInTerminal))
    # # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_attach))
    # test_suite.addTests(loader.loadTestsFromTestCase(TestDAP_launch_termination))
    # test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestBreakpoints))
    # test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestStackTraceAndScopes))
    # test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestVariableInspection))
    # test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestExpressionEvaluation))
    # test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSteppingOperations))
    # test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHandling))

    return test_suite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
