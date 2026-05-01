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
from typing import Any, Dict, Optional, TypeVar, cast

from lldb_dap.utils import DebugAdapter, DebugAdapterOptions

from . import configuration
from .session_helpers import DAPTestSession


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


def skipif_platform(oslist: list[str]):
    """Decorate the item to skip tests if running on one of the listed platforms."""
    # This decorator cannot be ported to `skipIf` yet because it is used on entire
    # classes, which `skipIf` explicitly forbids.
    oslist = [name.lower() for name in oslist]
    return unittest.skipIf(
        sys.platform.lower() in oslist, "skip on %s" % (", ".join(oslist))
    )


def skipif_darwin():
    return skipif_platform(["darwin"])


def skipif_linux():
    return skipif_platform(["linux"])


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

    @classmethod
    def setUpClass(cls):
        """Set up class-level resources"""
        dap_path = str(Path.home() / "Dev/contribute/llvm-build/release/bin/lldb-dap")
        if sys.platform == "darwin":
            dap_path = "/Volumes/workspace/Dev/llvm-build/release/bin/lldb-dap"

        cls.lldbDAPExec = os.getenv("DAP_ADAPTER_PATH", dap_path)
        cls.adapter_timeout = float(os.getenv("DAP_TIMEOUT", "100"))
        cls.run_as_server: bool = strtobool(os.getenv("DAP_RUN_AS_SERVER", "false"))
        cls.DEFAULT_TIMEOUT = cls.adapter_timeout
        module_file = sys.modules[cls.__module__].__file__
        assert module_file is not None
        cls.test_base_dir = Path(module_file).stem
        cls.oldcwd = os.getcwd()

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

        # Create DAP client

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

        self.session = DAPTestSession(
            self, self.test_dir, self.adapter, message_timeout=self.adapter_timeout
        )
        self.session.start()

    def tearDown(self):
        """Clean up after each test"""
        # TODO: WRITE warning that the session is still running before trying to close it
        self.session.stop()
        if self.adapter.is_alive:
            self.adapter.kill()

        # # Clean up temp directory
        # if self.test_dir and self.test_dir.exists():
        #     shutil.rmtree(self.test_dir)
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

    def build(self):
        assert self.TEST_PROGRAM is not None
        self.create_test_program_with_name("main.cpp")

    def create_debug_session(self, adapter: DebugAdapter) -> DAPTestSession:
        # TODO: ??
        """Create the lldb-dap debug adapter"""
        self.assertTrue(
            is_exe(self.lldbDAPExec), "lldb-dap must exist and be executable"
        )
        test_session = DAPTestSession(
            self,
            self.test_dir,
            adapter,
            message_timeout=self.adapter_timeout,
        )
        return test_session

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
        adapter_options = adapter_options.clone(log_file=log_file, cwd=cwd, env=env)

        adapter = DebugAdapter(executable=self.lldbDAPExec, opts=adapter_options)

        assert adapter.is_alive

        def cleanup():
            if adapter.is_alive:
                adapter.kill()

        self.addCleanup(cleanup)
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

    def start_debug_session(self, adapter_options: DebugAdapterOptions):
        self.adapter = self.create_adapter(adapter_options)
        self.session = self.create_debug_session(self.adapter)

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

    def compile_program(self, filepath: str, output_name: Optional[str] = None):
        assert self.test_dir is not None
        output_name = output_name or "a.out"
        output_path = self.getBuildArtifact(output_name)
        filepath = os.path.realpath(os.path.normpath(filepath))
        if filepath.endswith(".c"):
            compiler = "/usr/bin/clang"
        else:
            compiler = "/usr/bin/clang++"
        self.run_command([compiler, "-g", "-o", output_path, filepath])
        return str(self.test_dir / output_name)

    def expect_is_not_none(self, value: Optional[T], msg: Any = None) -> T:
        """Convenience function for getting fields that is optional. as most DAP types are"""
        self.assertIsNotNone(value, msg=msg)
        return cast(T, value)
