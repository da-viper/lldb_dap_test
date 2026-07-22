"""
Test the redirection of stdio.
There are three ways to launch the debuggee:
internalConsole, integratedTerminal and externalTerminal.

For each redirection configuration we exercise the stdin, argv, and env
input paths in a single launch. The C++ test program writes whatever it
receives from each available source. Assertions then check that every
applicable path arrived through the redirected stream.

NOTE: The testcases do not include all possible configurations of consoles.
"""

from abc import abstractmethod
from tempfile import NamedTemporaryFile

from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase, DAPTestSession
from lldbsuite.test.tools.lldb_dap.types import Console, LaunchArgs


class DAP_launchIO(DAPTestCaseBase):
    """Implements the redirection scenarios that are common to every console.

    Subclasses provide `console` and override `_get_debuggee_stdout` /
    `_get_debuggee_stderr` for the cases where stdout / stderr are not
    redirected to files (the streams have to be read from the console
    instead, which differs between InternalConsole and IntegratedTerminal).
    """

    TEST_PROGRAM = r"""
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

int main(int argc, char *argv[]) {
  // Parse args: an optional positional value, plus the flag --read-stdin.
  // The flag is set by tests that have wired up stdin redirection; without
  // it we never call getline, which would otherwise block on a pipe that's
  // open but empty (e.g. the test runner's stdin in runInTerminal mode).
  std::string arg_text;
  bool read_stdin = false;
  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--read-stdin") == 0) {
      read_stdin = true;
    } else if (arg_text.empty()) {
      arg_text = argv[i];
    }
  }

  if (!arg_text.empty()) {
    std::cout << "[STDOUT][FROM_ARGV]: " << arg_text << "\n";
    std::cerr << "[STDERR][FROM_ARGV]: " << arg_text << "\n";
  }
  if (const char *env = std::getenv("FROM_ENV")) {
    std::cout << "[STDOUT][FROM_ENV]: " << env << "\n";
    std::cerr << "[STDERR][FROM_ENV]: " << env << "\n";
  }
  if (read_stdin) {
    std::string line;
    if (std::getline(std::cin, line)) {
      std::cout << "[STDOUT][FROM_STDIN]: " << line << "\n";
      std::cerr << "[STDERR][FROM_STDIN]: " << line << "\n";
    }
  }
  return 0;
}
"""

    def setUp(self):
        super().setUp()

    def all_redirection(self, console: Console):
        """All three streams redirected to files. Verify every input path."""
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        stdin_text = "from stdin"
        args_text = "from argv"
        env_text = "from env"

        with NamedTemporaryFile("wt") as stdin, NamedTemporaryFile(
            "rt"
        ) as stdout, NamedTemporaryFile("rt") as stderr:
            stdin.write(stdin_text)
            stdin.flush()

            session.launch(
                LaunchArgs(
                    program,
                    stdio=[stdin.name, stdout.name, stderr.name],
                    console=console,
                    args=["--read-stdin", args_text],
                    env={"FROM_ENV": env_text},
                )
            )
            session.verify_process_exited()

            out = stdout.read()
            err = stderr.read()
            self.assertIn(f"[STDOUT][FROM_STDIN]: {stdin_text}", out)
            self.assertIn(f"[STDOUT][FROM_ARGV]: {args_text}", out)
            self.assertIn(f"[STDOUT][FROM_ENV]: {env_text}", out)

            self.assertIn(f"[STDERR][FROM_STDIN]: {stdin_text}", err)
            self.assertIn(f"[STDERR][FROM_ARGV]: {args_text}", err)
            self.assertIn(f"[STDERR][FROM_ENV]: {env_text}", err)

    def stdin_redirection(self, console: Console):
        """Only stdin redirected. Verify every input path via console output."""
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        stdin_text = "from stdin"
        args_text = "from argv"
        env_text = "from env"

        with NamedTemporaryFile("w+t") as stdin:
            stdin.write(stdin_text)
            stdin.flush()
            session.launch(
                LaunchArgs(
                    program,
                    stdio=[stdin.name],
                    console=console,
                    args=["--read-stdin", args_text],
                    env={"FROM_ENV": env_text},
                )
            )
            session.verify_process_exited()

            out = self._get_debuggee_stdout(session)
            err = self._get_debuggee_stderr(session)
            self.assertIn(f"[STDOUT][FROM_STDIN]: {stdin_text}", out)
            self.assertIn(f"[STDOUT][FROM_ARGV]: {args_text}", out)
            self.assertIn(f"[STDOUT][FROM_ENV]: {env_text}", out)

            self.assertIn(f"[STDERR][FROM_STDIN]: {stdin_text}", err)
            self.assertIn(f"[STDERR][FROM_ARGV]: {args_text}", err)
            self.assertIn(f"[STDERR][FROM_ENV]: {env_text}", err)

    def stdout_redirection(self, console: Console):
        """Only stdout redirected. Verify argv and env paths.

        stdin is not set up — the C++ program skips reading it because the
        file descriptor is a tty (would block).
        """
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        args_text = "from argv"
        env_text = "from env"

        with NamedTemporaryFile("rt") as stdout:
            session.launch(
                LaunchArgs(
                    program,
                    stdio=[None, stdout.name],
                    console=console,
                    args=[args_text],
                    env={"FROM_ENV": env_text},
                )
            )
            session.verify_process_exited()

            out = stdout.read()
            err = self._get_debuggee_stderr(session)
            self.assertIn(f"[STDOUT][FROM_ARGV]: {args_text}", out)
            self.assertIn(f"[STDOUT][FROM_ENV]: {env_text}", out)

            self.assertIn(f"[STDERR][FROM_ARGV]: {args_text}", err)
            self.assertIn(f"[STDERR][FROM_ENV]: {env_text}", err)

    def stderr_redirection(self, console: Console):
        """Only stderr redirected. Verify argv and env paths."""
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")
        args_text = "from argv"
        env_text = "from env"

        with NamedTemporaryFile("rt") as stderr:
            session.launch(
                LaunchArgs(
                    program,
                    stdio=[None, None, stderr.name],
                    console=console,
                    args=[args_text],
                    env={"FROM_ENV": env_text},
                )
            )
            session.verify_process_exited()

            out = self._get_debuggee_stdout(session)
            err = stderr.read()
            self.assertIn(f"[STDOUT][FROM_ARGV]: {args_text}", out)
            self.assertIn(f"[STDOUT][FROM_ENV]: {env_text}", out)

            self.assertIn(f"[STDERR][FROM_ARGV]: {args_text}", err)
            self.assertIn(f"[STDERR][FROM_ENV]: {env_text}", err)

    @abstractmethod
    def _get_debuggee_stdout(self, session: DAPTestSession) -> str:
        """Retrieves the standard output (stdout) from the debuggee process.

        The default destination of the debuggee's stdout can vary based on how the debuggee
        was launched (either a debug console or a pseudo-terminal (pty)).
        It requires subclasses to implement the specific mechanism for obtaining the stdout stream.
        """
        raise RuntimeError(f"NotImplemented for {self}")

    @abstractmethod
    def _get_debuggee_stderr(self, session: DAPTestSession) -> str:
        """Retrieves the standard error (stderr) from the debuggee process.

        The default destination of the debuggee's stderr can vary based on how the debuggee
        was launched (either a debug console or a pseudo-terminal (pty)).
        It requires subclasses to implement the specific mechanism for obtaining the stderr stream.
        """
        raise RuntimeError(f"NotImplemented for {self}")
