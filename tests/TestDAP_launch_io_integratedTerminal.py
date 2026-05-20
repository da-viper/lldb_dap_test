"""
Test the redirection after launching in the integrated terminal.
"""

from lldb_dap.dap_types import Console
from tests.DAP_launch_io import DAP_launchIO
from lldbsuite.test.decorators import (
    skipIfAsan,
    skipIfBuildType,
    skipIfRemote,
    skipIfWindows,
)


@skipIfRemote
@skipIfAsan
@skipIfBuildType(["debug"])
@skipIfWindows
class TestDAP_launch_io_IntegratedTerminal(DAP_launchIO):
    console = Console.INTEGRATED_TERMINAL

    # all redirection
    def test_all_redirection(self):
        self.all_redirection(console=self.console)

    def test_all_redirection_with_args(self):
        self.all_redirection(console=self.console, with_args=True)

    # stdin
    def test_stdin_redirection(self):
        self.stdin_redirection(console=self.console)

    def test_stdin_redirection_with_args(self):
        self.stdin_redirection(console=self.console, with_args=True)

    # stdout
    def test_stdout_redirection(self):
        self.stdout_redirection(console=self.console)

    def test_stdout_redirection_with_env(self):
        self.stdout_redirection(console=self.console, with_env=True)

    # stderr
    def test_stderr_redirection(self):
        self.stderr_redirection(console=self.console)

    def test_stderr_redirection_with_env(self):
        self.stderr_redirection(console=self.console, with_env=True)

    def _get_debuggee_stdout(self) -> str:
        return self.session.get_stdout()

    def _get_debuggee_stderr(self) -> str:
        return self.session.get_stderr()
