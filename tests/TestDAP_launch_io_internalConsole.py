"""
Test the redirection after launching in the internal console.
"""

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.tools.lldb_dap.dap_types import Console


try:
    from DAP_launch_io import DAP_launchIO
except ModuleNotFoundError:
    from .DAP_launch_io import DAP_launchIO

@skipIfWindows
class TestDAP_launch_io_InternalConsole(DAP_launchIO):
    console = Console.INTERNAL

    def test_all_redirection(self):
        self.all_redirection(console=self.console)

    def test_stdin_redirection(self):
        self.stdin_redirection(console=self.console)

    def test_stdout_redirection(self):
        self.stdout_redirection(console=self.console)

    def test_stderr_redirection(self):
        self.stderr_redirection(console=self.console)

    def _get_debuggee_stdout(self) -> str:
        return self._session.get_stdout()

    def _get_debuggee_stderr(self) -> str:
        # NOTE: In internalConsole stderr writes to stdout.
        return self._get_debuggee_stdout()
