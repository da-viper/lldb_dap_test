"""
Test lldb-dap moduleSymbols request
"""

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.tools.lldb_dap.dap_types import LaunchArgs, ModuleSymbolsArgs
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase


class TestDAP_moduleSymbols(DAPTestCaseBase):
    TEST_PROGRAM = r"""
int func1() { return 42; }

int func2() { return 84; }

int main() {
  func1();
  func2();
  return 0;
}
"""
    IS_C = True

    # On windows LLDB doesn't recognize symbols in a.out.
    @skipIfWindows
    def test_moduleSymbols(self):
        """
        Test that the moduleSymbols request returns correct symbols from the module.
        """
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        session.launch(LaunchArgs(program=program))

        symbol_names = set()
        start = 0
        page_size = 100
        while True:
            response = session.send_request(
                ModuleSymbolsArgs(moduleName="a.out", startIndex=start, count=page_size)
            ).result()
            symbols = response.body.symbols
            symbol_names.update(sym.name for sym in symbols)

            if len(symbols) < page_size:
                break
            start += page_size

        expected_symbol_names = {"main", "func1", "func2"}
        self.assertTrue(
            expected_symbol_names.issubset(symbol_names),
            f"expected symbols missing; got {symbol_names!r}",
        )
