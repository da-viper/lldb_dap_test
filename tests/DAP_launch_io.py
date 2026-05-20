"""
Test the redirection of stdio.
There are three ways to launch the debuggee
internalConsole, integratedTerminal and externalTerminal.

For the three configurations, we test if we can read data
from environments, stdin and cli arguments.

NOTE: The testcases do not include all possible configurations of
consoles, environments, stdin and cli arguments.
"""

from lldb_dap.dap_types import Console
from lldb_dap.dap_types import LaunchArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from abc import abstractmethod
from tempfile import NamedTemporaryFile


class DAP_launchIO(DAPTestCaseBase):
    """The class holds the implementation different ways to redirect the debuggee I/O streams
    which is configurable from the Derived classes.

    Depending on the console type the output will be in different places.
    It also provides two abstract functions `_get_debuggee_stdout` and `_get_debuggee_stderr`
    that provides the debuggee stdout and stderr.
    """

    TEST_PROGRAM = r"""
#include <cstdlib>
#include <iostream>

int main(int argc, char *argv[]) {
  const bool use_stdin = argc <= 1;
  const char *use_env = std::getenv("FROM_ENV");

  if (use_env != nullptr) { // from environment variable
    std::cout << "[STDOUT][FROM_ENV]: " << use_env;
    std::cerr << "[STDERR][FROM_ENV]: " << use_env;

  } else if (use_stdin) { // from standard in
    std::string line;
    std::getline(std::cin, line);
    std::cout << "[STDOUT][FROM_STDIN]: " << line;
    std::cerr << "[STDERR][FROM_STDIN]: " << line;

  } else { // from argv
    const char *first_arg = argv[1];
    std::cout << "[STDOUT][FROM_ARGV]: " << first_arg;
    std::cerr << "[STDERR][FROM_ARGV]: " << first_arg;
  }
  return 0;
}

"""
    def setUp(self):
        super().setUp()
        self.session = self.build_and_create_session()

    def all_redirection(self, console: Console, with_args: bool = False):
        """Test all standard io redirection."""
        program = self.getBuildArtifact("a.out")
        input_text = "from stdin with redirection"
        args_text = "string from argv"
        program_args = [args_text] if with_args else None

        with NamedTemporaryFile("wt") as stdin, NamedTemporaryFile(
            "rt"
        ) as stdout, NamedTemporaryFile("rt") as stderr:
            stdin.write(input_text)
            stdin.flush()
            self.session.launch_using_config(
                LaunchArgs(
                    program,
                    stdio=[stdin.name, stdout.name, stderr.name],
                    console=console,
                    args=program_args,
                )
            )
            self.session.verify_process_exited()

            all_stdout = stdout.read()
            all_stderr = stderr.read()

            if with_args:
                self.assertEqual(f"[STDOUT][FROM_ARGV]: {args_text}", all_stdout)
                self.assertEqual(f"[STDERR][FROM_ARGV]: {args_text}", all_stderr)

                self.assertNotIn(f"[STDOUT][FROM_ARGV]: {args_text}", all_stderr)
                self.assertNotIn(f"[STDERR][FROM_ARGV]: {args_text}", all_stdout)

            else:
                self.assertEqual(f"[STDOUT][FROM_STDIN]: {input_text}", all_stdout)
                self.assertEqual(f"[STDERR][FROM_STDIN]: {input_text}", all_stderr)

                self.assertNotIn(f"[STDERR][FROM_STDIN]: {input_text}", all_stdout)
                self.assertNotIn(f"[STDOUT][FROM_STDIN]: {input_text}", all_stderr)

    def stdin_redirection(self, console: Console, with_args: bool = False):
        """Test only stdin redirection."""
        program = self.getBuildArtifact("a.out")
        input_text = "string from stdin"
        args_text = "string from argv"
        program_args = [args_text] if with_args else None

        with NamedTemporaryFile("w+t") as stdin:
            stdin.write(input_text)
            stdin.flush()
            self.session.launch_using_config(
                LaunchArgs(
                    program, stdio=[stdin.name], console=console, args=program_args
                )
            )
            self.session.verify_process_exited()

            stdout_text = self._get_debuggee_stdout()
            stderr_text = self._get_debuggee_stderr()

            if with_args:
                self.assertIn(f"[STDOUT][FROM_ARGV]: {args_text}", stdout_text)
                self.assertIn(f"[STDERR][FROM_ARGV]: {args_text}", stderr_text)
            else:
                self.assertIn(f"[STDOUT][FROM_STDIN]: {input_text}", stdout_text)
                self.assertIn(f"[STDERR][FROM_STDIN]: {input_text}", stderr_text)

    def stdout_redirection(self, console: Console, with_env: bool = False):
        """Test only stdout redirection."""
        program = self.getBuildArtifact("a.out")

        argv_text = "output with\n multiline"
        # By default unix terminals the ONLCR flag is enabled. which replaces '\n' with '\r\n'
        # see https://man7.org/linux/man-pages/man3/termios.3.html.
        # This does not affect writing to normal files.
        argv_replaced_text = argv_text.replace("\n", "\r\n")

        program_args = [argv_text]
        env_text = "string from env"
        env = {"FROM_ENV": env_text} if with_env else {}

        with NamedTemporaryFile("rt") as stdout:
            self.session.launch_using_config(
                LaunchArgs(
                    program,
                    stdio=[None, stdout.name],
                    console=console,
                    args=program_args,
                    env=env,
                )
            )
            self.session.verify_process_exited()

            # check stdout
            stdout_text = stdout.read()
            stderr_text = self._get_debuggee_stderr()
            if with_env:
                self.assertIn(f"[STDOUT][FROM_ENV]: {env_text}", stdout_text)
                self.assertIn(f"[STDERR][FROM_ENV]: {env_text}", stderr_text)

                self.assertNotIn(f"[STDERR][FROM_ENV]: {env_text}", stdout_text)
                self.assertNotIn(f"[STDOUT][FROM_ENV]: {env_text}", stderr_text)
            else:
                self.assertIn(f"[STDOUT][FROM_ARGV]: {argv_text}", stdout_text)

                self.assertNotIn(
                    f"[STDERR][FROM_ARGV]: {argv_replaced_text}", stdout_text
                )
                self.assertNotIn(f"[STDOUT][FROM_ARGV]: {argv_text}", stderr_text)

            # check stderr
            stderr_text = self._get_debuggee_stderr()
            # FIXME: when using 'integrated' or 'external' terminal we do not correctly
            # escape newlines that are sent to the terminal.
            if console == "integratedConsole":
                if with_env:
                    self.assertNotIn(f"[STDOUT][FROM_ENV]: {env_text}", stderr_text)
                    self.assertIn(f"[STDERR][FROM_ENV]: {env_text}", stderr_text)
                else:
                    self.assertNotIn(
                        f"[STDOUT][FROM_ARGV]: {argv_replaced_text}", stderr_text
                    )
                    self.assertIn(
                        f"[STDERR][FROM_ARGV]: {argv_replaced_text}", stderr_text
                    )

    def stderr_redirection(self, console: Console, with_env: bool = False):
        """Test only stdout redirection."""
        program = self.getBuildArtifact("a.out")

        argv_text = "output with\n multiline"
        # By default unix terminals the ONLCR flag is enabled. which replaces '\n' with '\r\n'
        # see https://man7.org/linux/man-pages/man3/termios.3.html.
        # This does not affect writing to normal files.
        # Currently out test implementation for external and integrated Terminal does not run the
        # program through a shell terminal.
        argv_replaced_text = argv_text
        if console == "internalConsole":
            argv_replaced_text = argv_text.replace("\n", "\r\n")
        program_args = [argv_text]
        env_text = "string from env"
        env = {"FROM_ENV": env_text} if with_env else {}

        with NamedTemporaryFile("rt") as stderr:
            self.session.launch_using_config(
                LaunchArgs(
                    program,
                    stdio=[None, None, stderr.name],
                    console=console,
                    args=program_args,
                    env=env,
                )
            )
            self.session.verify_process_exited()
            stdout_text = self._get_debuggee_stdout()
            stderr_text = stderr.read()
            if with_env:
                self.assertIn(f"[STDOUT][FROM_ENV]: {env_text}", stdout_text)
                self.assertIn(f"[STDERR][FROM_ENV]: {env_text}", stderr_text)
            else:
                self.assertIn(f"[STDOUT][FROM_ARGV]: {argv_replaced_text}", stdout_text)
                self.assertIn(f"[STDERR][FROM_ARGV]: {argv_text}", stderr_text)

    @abstractmethod
    def _get_debuggee_stdout(self) -> str:
        """Retrieves the standard output (stdout) from the debuggee process.

        The default destination of the debuggee's stdout can vary based on how the debugger
        was launched (either a debug console or a pseudo-terminal (pty)).
        It requires subclasses to implement the specific mechanism for obtaining the stdout stream.
        """
        raise RuntimeError(f"NotImplemented for {self}")

    @abstractmethod
    def _get_debuggee_stderr(self) -> str:
        """Retrieves the standard error (stderr) from the debuggee process.

        The default destination of the debuggee's stderr can vary based on how the debugger
        was launched (either a debug console or a pseudo-terminal (pty)).
        It requires subclasses to implement the specific mechanism for obtaining the stderr stream.
        """
        raise RuntimeError(f"NotImplemented for {self}")
