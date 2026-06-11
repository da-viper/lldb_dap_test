from __future__ import annotations
import gc
import io
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
from subprocess import DEVNULL, PIPE, Popen
import subprocess
import sys
import time
from typing import Callable, Optional, Tuple
import unittest

from lldbsuite.test import configuration
from lldbsuite.test import lldbplatformutil


def line_number(filename, string_to_match):
    """Helper function to return the line number of the first matched string."""
    with io.open(filename, mode="r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.find(string_to_match) != -1:
                # Found our match.
                return i + 1
    raise Exception("Unable to find '%s' within file %s" % (string_to_match, filename))


def is_exe(fpath: str):
    """Returns true if fpath is an executable."""
    if fpath is None:
        return False
    if sys.platform == "win32":
        if not fpath.endswith(".exe"):
            fpath += ".exe"
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)


COMMAND_FAILED_AS_EXPECTED = "Command has failed as expected"

CURRENT_EXECUTABLE_SET = "Current executable set successfully"

PROCESS_IS_VALID = "Process is valid"

PROCESS_KILLED = "Process is killed successfully"

PROCESS_EXITED = "Process exited successfully"

PROCESS_STOPPED = "Process status should be stopped"

RUN_SUCCEEDED = "Process is launched successfully"

RUN_COMPLETED = "Process exited successfully"

BACKTRACE_DISPLAYED_CORRECTLY = "Backtrace displayed correctly"

BREAKPOINT_CREATED = "Breakpoint created successfully"

BREAKPOINT_STATE_CORRECT = "Breakpoint state is correct"

BREAKPOINT_PENDING_CREATED = "Pending breakpoint created successfully"

BREAKPOINT_HIT_ONCE = "Breakpoint resolved with hit count = 1"

BREAKPOINT_HIT_TWICE = "Breakpoint resolved with hit count = 2"

BREAKPOINT_HIT_THRICE = "Breakpoint resolved with hit count = 3"


class _LocalProcess:
    def __init__(self, trace_on):
        self._proc: Optional[Popen] = None
        self._trace_on = trace_on
        self._delayafterterminate = 0.1

    @property
    def pid(self):
        assert self._proc is not None, "No process"
        return self._proc.pid

    @property
    def stdout(self):
        assert self._proc is not None, "No process"
        return self._proc.stdout

    @property
    def stderr(self):
        assert self._proc is not None, "No process"
        return self._proc.stderr

    def launch(self, executable, args, extra_env, **kwargs):
        env = None
        if extra_env:
            env = dict(os.environ)
            env.update([kv.split("=", 1) for kv in extra_env])

        stdout = kwargs.pop("stdout", DEVNULL if not self._trace_on else None)
        stderr = kwargs.pop("stderr", None)
        # This works around a bug in the macOS job control code where
        # a supurious SIGHUP is sent to the the process group of our
        # spawned subprocess when it is shutting down.
        # While this SIGHUP doesn't cause any issues for our subprocess,
        # it does reach the LIT process and stops the test suite run
        # early.
        # This parameter forces the spawned process into a new process
        # group which prevents the supurious SIGHUP from reaching LIT.
        # We don't
        kwargs.setdefault("start_new_session", True)

        self._proc = Popen(
            [executable] + args,
            stdout=stdout,
            stderr=stderr,
            stdin=PIPE,
            env=env,
            **kwargs,
        )

    def terminate(self):
        if self._proc is None:
            return

        if self._proc.poll() is None:
            # Terminate _proc like it does the pexpect
            signals_to_try = [
                sig for sig in ["SIGHUP", "SIGCONT", "SIGINT"] if sig in dir(signal)
            ]
            for sig in signals_to_try:
                try:
                    self._proc.send_signal(getattr(signal, sig))
                    time.sleep(self._delayafterterminate)
                    if self._proc.poll() is not None:
                        return
                except ValueError:
                    pass  # Windows says SIGINT is not a valid signal to send
            self._proc.terminate()
            time.sleep(self._delayafterterminate)
            if self._proc.poll() is not None:
                return
            self._proc.kill()
            time.sleep(self._delayafterterminate)

    def communicate(
        self, input: Optional[str] = None, timeout: Optional[float] = None
    ) -> Tuple[bytes, bytes]:
        assert self._proc is not None
        return self._proc.communicate(input, timeout)

    def poll(self):
        assert self._proc is not None
        return self._proc.poll()

    def wait(self, timeout=None):
        assert self._proc is not None
        return self._proc.wait(timeout)

    def kill(self):
        assert self._proc is not None
        return self._proc.kill()


class Base(unittest.TestCase):
    TEST_PROGRAM: str
    IS_C = False

    @property
    def lastSubprocess(self):
        return self.subprocesses[-1] if len(self.subprocesses) > 0 else None

    def spawnSubprocess(
        self, executable, args=None, extra_env=None, install_remote=True, **kwargs
    ):
        """Creates a subprocess.Popen object with the specified executable and arguments,
        saves it in self.subprocesses, and returns the object.
        """
        args = [] if args is None else args
        proc = _LocalProcess(self.TraceOn())
        proc.launch(executable, args, extra_env=extra_env, **kwargs)
        self.subprocesses.append(proc)
        return proc

    def TraceOn(self):
        """Returns True if we are in trace mode (tracing detailed test execution)."""
        return False

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources"""

        module_file = sys.modules[cls.__module__].__file__
        assert module_file is not None
        cls.test_base_dir = Path(module_file).stem
        cls.oldcwd = os.getcwd()

        # Set platform context.
        cls.platformContext = lldbplatformutil.createPlatformContext()

        dap_path = str(Path.home() / "Dev/contribute/llvm-build/release/bin/lldb-dap")
        if sys.platform == "darwin":
            dap_path = "/Volumes/workspace/Dev/llvm-build/release/bin/lldb-dap"

        cls.lldbDAPExec = os.getenv("DAP_ADAPTER_PATH", dap_path)

    def setUp(self):
        super().setUp()
        """Set up each test"""
        # Create temporary directory for test files
        self.test_dir = (
            configuration.test_build_dir / self.test_base_dir / self._testMethodName
        )
        if self.test_dir and self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self._source_dir = self.test_dir / "source"
        os.makedirs(self._source_dir)
        os.chdir(str(self._source_dir))
        # List of spawned subproces.Popen objects
        self.subprocesses = []

    def cleanupSubprocesses(self):
        # Terminate subprocesses in reverse order from how they were created.
        for p in reversed(self.subprocesses):
            p.terminate()
            del p
        del self.subprocesses[:]

    def tearDown(self):
        """Clean up after each test"""
        # Remove subprocesses created by the test.
        self.cleanupSubprocesses()
        super(Base, self).tearDown()
        gc.collect()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        unittest.TestCase.tearDownClass()
        os.chdir(cls.oldcwd)

    @classmethod
    def setUpCommands(cls):
        commands = [
            # First of all, clear all settings to have clean state of global properties.
            "settings clear --all",
            # Disable Spotlight lookup. The testsuite creates
            # different binaries with the same UUID, because they only
            # differ in the debug info, which is not being hashed.
            "settings set symbols.enable-external-lookup false",
            # Inherit the TCC permissions from the inferior's parent.
            "settings set target.inherit-tcc true",
            # Based on https://discourse.llvm.org/t/running-lldb-in-a-container/76801/4
            "settings set target.disable-aslr false",
            # Kill rather than detach from the inferior if something goes wrong.
            "settings set target.detach-on-error false",
            # Disable fix-its by default so that incorrect expressions in tests don't
            # pass just because Clang thinks it has a fix-it.
            "settings set target.auto-apply-fixits false",
            # Testsuite runs in parallel and the host can have also other load.
            "settings set plugin.process.gdb-remote.packet-timeout 60",
            # Disable colors by default.
            "settings set use-color false",
            # Disable the statusline by default.
            "settings set show-statusline false",
            "settings set target.check-vo-ownership true",
        ]

        return commands

    def getPlatform(self):
        return sys.platform

    def platformIsDarwin(self):
        """Returns true if the OS triple for the selected platform is any valid apple OS"""
        return lldbplatformutil.platformIsDarwin()

    def getBuildArtifact(self, name: str = "a.out"):
        return os.path.join(self.getBuildDir(), name)

    def getLogBasenameForCurrentTest(self, prefix="norm"):
        """
        returns a partial path that can be used as the beginning of the name of multiple
        log files pertaining to this test
        """
        return os.path.join(self.getBuildDir(), prefix)

    def getBuildDir(self):
        return str(self.test_dir)

    def getSourcePath(self, filename: str):
        return str(self._source_dir / filename)

    def getArchitecture(self):
        return platform.machine()

    def yaml2obj(self, yaml_path: str, obj_path: str, max_size=None):
        """
        Create an object file at the given path from a yaml file.

        Throws subprocess.CalledProcessError if the object could not be created.
        """
        yaml2obj_bin = configuration.get_yaml2obj_path()
        if not yaml2obj_bin:
            self.assertTrue(False, "No valid yaml2obj executable specified")
        command = [yaml2obj_bin, "-o=%s" % obj_path, yaml_path]
        if max_size is not None:
            command += ["--max-size=%d" % max_size]
        self.run_command(command)

    def run_command(self, command_args: list[str]):
        result = subprocess.run(command_args, cwd=self.getSourcePath(""))
        if result.returncode != 0:
            args = " ".join(result.args)
            raise Exception(f"{result}\n{args}")

    def build(self, filename: Optional[str] = None):
        assert self.TEST_PROGRAM is not None
        opt_filename = "main.c" if self.IS_C else "main.cpp"
        filename = filename or opt_filename
        self.create_test_program_with_name(filename)

    def run_platform_command(self, cmd: str):
        commands = shlex.split(cmd)
        result = subprocess.run(commands, cwd=self.getBuildDir())
        stderr = "" if result.stderr is None else result.stderr.decode()
        stdout = "" if result.stdout is None else result.stdout.decode()
        return stderr, result.returncode, stdout

    def create_test_program_with_name(self, filename: str):
        file = self.create_file(self.TEST_PROGRAM, filename)
        return self.compile_program(file)

    def create_and_compile_file(self, code: str, filename: str = "main.cpp"):
        file = self.create_file(code, filename)
        return self.compile_program(file)

    def create_file(self, code: str, filename: str) -> str:
        """Create a test program file"""
        program_path = Path(self.getSourcePath(filename))
        program_path.write_text(code)
        return str(program_path)

    def compile_program(
        self,
        filepath: str,
        output_name: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
    ):
        assert self.test_dir is not None
        output_name = output_name or "a.out"
        output_path = self.getBuildArtifact(output_name)
        filepath = os.path.realpath(os.path.normpath(filepath))
        if filepath.endswith(".c"):
            compiler = "/usr/bin/clang"
        else:
            compiler = "/usr/bin/clang++"

        commands = [compiler, "-g"]
        if extra_args is not None:
            commands.extend(extra_args)
        commands.extend(["-o", output_path, filepath])

        self.run_command(commands)
        return str(self.test_dir / output_name)

    def addTearDownHook(self, func: Callable):
        self.addCleanup(func)
