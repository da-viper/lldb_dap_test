"""
Test lldb-dap moduleSymbols request
"""

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs, ModuleSymbolsArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


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
            module_sym_args = ModuleSymbolsArgs(
                moduleName="a.out", startIndex=start, count=page_size
            )
            response = session.send_request(module_sym_args).result()
            symbols = response.body.symbols
            symbol_names.update(sym.name for sym in symbols)

            if len(symbols) < page_size:
                break
            start += page_size

        for expected_symbol in ["main", "func1", "func2"]:
            self.assertIn(expected_symbol, symbol_names)
