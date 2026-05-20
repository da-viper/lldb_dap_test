from __future__ import annotations

import copy
import gc
import io
import os
import platform
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, cast
from typing import Type

from lldb_dap.dap_types import ErrorResponse
from lldb_dap.utils import DebugAdapter, DebugAdapterOptions

from . import configuration
from .session_helpers import DAPTestSession


def is_exe(fpath: str):
    """Returns true if fpath is an executable."""
    if fpath is None:
        return False
    if sys.platform == "win32":
        if not fpath.endswith(".exe"):
            fpath += ".exe"
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)


def strtobool(val: str) -> bool:
    """Convert a string representation of truth to a bool following LLVM's CLI argument parsing."""

    val = val.lower()
    if val in ["false", "0"]:
        return False
    return True


T = TypeVar("T")


class DAPTestCaseBase(unittest.TestCase):
    """Base test case for DAP tests"""

    TEST_PROGRAM: str
    # The environment variables that is set when launching the
    # debug adapter in create_debug_adapter.
    LLDB_DAP_ENV: Dict[str, str] = {}
    IS_C = False

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources"""
        dap_path = str(Path.home() / "Dev/contribute/llvm-build/release/bin/lldb-dap")
        if sys.platform == "darwin":
            dap_path = "/Volumes/workspace/Dev/llvm-build/release/bin/lldb-dap"

        cls.lldbDAPExec = os.getenv("DAP_ADAPTER_PATH", dap_path)
        cls.DEFAULT_TIMEOUT = float(os.getenv("DAP_TIMEOUT", "30"))

        cls.run_as_server: bool = strtobool(os.getenv("DAP_RUN_AS_SERVER", "true"))
        module_file = sys.modules[cls.__module__].__file__
        assert module_file is not None
        cls.test_base_dir = Path(module_file).stem
        cls.oldcwd = os.getcwd()

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

    def setUp(self):
        """Set up each test"""
        # Create temporary directory for test files
        self.test_dir = (
            configuration.test_build_dir / self.test_base_dir / self._testMethodName
        )
        self._debug_adapter_count: int = 0
        if self.test_dir and self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self._source_dir = self.test_dir / "source"
        os.makedirs(self._source_dir)
        os.chdir(str(self._source_dir))

        # Create Debug Adapter.
        if self.run_as_server:
            # Launch using socket.
            self.adapter = self.create_adapter_in_server_mode(
                DebugAdapterOptions(cwd=self.getBuildDir()),
                connection="listen://localhost:0",
                connection_timeout=10,
            )
        else:
            # Launch using stdio.
            self.adapter = self.create_adapter_in_stdio_mode(
                DebugAdapterOptions(cwd=self.getBuildDir())
            )

    def create_session(
        self,
        adapter: Optional[DebugAdapter] = None,
        disconnect_automatically: Optional[bool] = None,
    ) -> DAPTestSession:
        if adapter is None:
            self.assertIsNotNone(self.adapter, "expected we already have an adapter.")
            adapter = self.adapter
        self.assertTrue(adapter.is_alive, "expected adapter process is alive.")

        if adapter.is_server and disconnect_automatically is not None:
            self.assertFalse(
                disconnect_automatically,
                "disconnect_automatically is not supported for lldb-dap running as a server",
            )

        session = DAPTestSession(
            self, self.test_dir, adapter, message_timeout=self.DEFAULT_TIMEOUT
        )

        def cleanup_session():
            # In server mode the adapter automatically shuts down after the last
            # client disconnects.
            if not adapter.is_server and disconnect_automatically:
                session.do_disconnect(terminateDebuggee=True)
            session.stop()

        self.addTearDownHook(cleanup_session)
        session.start()
        return session

    def build_and_create_session(
        self,
        adapter: Optional[DebugAdapter] = None,
        disconnect_automatically: Optional[bool] = None,
    ):
        self.build()
        return self.create_session(adapter, disconnect_automatically)

    def tearDown(self):
        """Clean up after each test"""

        gc.collect()
        super(DAPTestCaseBase, self).tearDown()

    @classmethod
    def tearDownClass(cls):
        unittest.TestCase.tearDownClass()
        os.chdir(cls.oldcwd)

    def getPlatform(self):
        return sys.platform

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

    def build(self, filename: Optional[str] = None):
        assert self.TEST_PROGRAM is not None
        opt_filename = "main.c" if self.IS_C else "main.cpp"
        filename = filename or opt_filename
        self.create_test_program_with_name(filename)

    def create_adapter(self, adapter_options: DebugAdapterOptions):
        self.assertTrue(
            is_exe(self.lldbDAPExec),
            f"lldb-dap must exist and be executable. path: {self.lldbDAPExec}",
        )

        if not adapter_options.log_file:
            adapter_count = self._debug_adapter_count
            if adapter_count == 0:
                log_file = f"{self.getLogBasenameForCurrentTest()}-dap.log"
            else:
                log_file = (
                    f"{self.getLogBasenameForCurrentTest()}-dap-{adapter_count}.log"
                )
        else:
            log_file = adapter_options.log_file

        self._debug_adapter_count += 1
        cwd = adapter_options.cwd or str(self.test_dir)
        env = copy.deepcopy(adapter_options.env)
        # Tests may add new environment variables.
        env.update(self.LLDB_DAP_ENV)
        args : List[str] = []
        for command in self.setUpCommands():
            args.extend(["--pre-init-command", command])
        args.extend(adapter_options.args)

        adapter_options = adapter_options.clone(
            log_file=log_file, cwd=cwd, env=env, args=args
        )

        adapter = DebugAdapter(executable=self.lldbDAPExec, opts=adapter_options)

        assert adapter.is_alive

        def cleanup_adapter():
            if adapter.is_alive:
                adapter.kill()

        self.addTearDownHook(cleanup_adapter)
        return adapter

    def create_adapter_in_stdio_mode(self, adapter_options: DebugAdapterOptions):
        """Forces the adapter to stdio mode. the DebugAdapter class handles the validation"""
        assert (
            adapter_options.connection is None
        ), "'connection' cannot be used with stdio mode"

        adapter = self.create_adapter(adapter_options)
        assert not adapter.is_server, "adapter should be using stdio"
        return adapter

    def create_adapter_in_server_mode(
        self,
        adapter_options: DebugAdapterOptions,
        *,
        connection: str,
        connection_timeout: int,
    ) -> DebugAdapter:
        """Forces the adapter to server mode. the DebugAdapter class handles the validation"""

        adapter_options = adapter_options.clone(
            connection=connection,
            connection_timeout=connection_timeout,
        )

        adapter = self.create_adapter(adapter_options)
        assert adapter.is_server
        return adapter

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

    def run_command(self, command_args: list[str]):
        result = subprocess.run(command_args, cwd=self.getSourcePath(""))
        if result.returncode != 0:
            args = " ".join(result.args)
            raise Exception(f"{result}\n{args}")

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

    def expect_is_not_none(self, value: Optional[T], msg: Any = None) -> T:
        """Convenience function for getting fields that is optional. as most DAP types are"""
        self.assertIsNotNone(value, msg=msg)
        return cast(T, value)

    def expect_error_response(
        self, value: object | ErrorResponse, msg: Any = None
    ) -> ErrorResponse:
        """Convenience function for narrowing a response Union to `ErrorRespones`."""
        self.assertIsInstance(value, ErrorResponse, msg=msg)
        return cast(ErrorResponse, value)

    def expect_success_response(self, value: T | ErrorResponse, msg: Any = None) -> T:
        """Convenience function for narrowing a response Union to the success type."""
        self.assertNotIsInstance(value, ErrorResponse, msg=msg)
        return cast(T, value)
    