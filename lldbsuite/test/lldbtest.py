from __future__ import annotations
from functools import wraps
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
from typing import Any, Callable, Dict, Optional, Tuple
import unittest

from lldbsuite.test import configuration, decorators
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
        cls.lldbDAPExec = configuration.lldbDAPExec

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
        return lldbplatformutil.getPlatform()

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

    def getSourceDir(self) -> str:
        """Return the full path to the current test."""
        return str(self._source_dir)

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
        result = subprocess.run(
            command_args, capture_output=True, cwd=self.getSourcePath("")
        )
        if result.returncode != 0:
            stderr = result.stderr.decode() if result.stderr else ""
            stdout = result.stdout.decode() if result.stdout else ""
            args = " ".join(result.args)

            raise Exception(f"{stderr}\n\tstdout:{stdout}\n\targs: {args}")

    def build(self, dictionary: Optional[Dict[str, Any]] = None):
        dictionary = dictionary or {}
        default = {
            "EXE": "a.out",
            "filename": "main.c" if self.IS_C else "main.cpp",
        }
        for key, value in default.items():
            dictionary.setdefault(key, value)

        assert self.TEST_PROGRAM is not None
        filename = dictionary["filename"]
        exe = dictionary["EXE"]
        self.create_and_compile_file(
            self.TEST_PROGRAM, filename=filename, output_name=exe
        )

    def run_platform_command(self, cmd: str):
        commands = shlex.split(cmd)
        result = subprocess.run(commands, cwd=self.getBuildDir())
        stderr = "" if result.stderr is None else result.stderr.decode()
        stdout = "" if result.stdout is None else result.stdout.decode()
        return stderr, result.returncode, stdout

    def create_test_program_with_name(self, filename: str):
        file = self.create_file(self.TEST_PROGRAM, filename)
        return self.compile_program(file)

    def create_and_compile_file(
        self, code: str, filename: str = "main.cpp", output_name: str = "a.out"
    ):
        file = self.create_file(code, filename)
        return self.compile_program(file, output_name=output_name)

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
        commands.extend([filepath, "-o", output_path])

        self.run_command(commands)
        return output_path

    def addTearDownHook(self, func: Callable):
        self.addCleanup(func)


def _expand_test_variants(attrname, methods, variant, xfail_fns, skip_fns):
    """Expand test methods in *methods* along the given *variant* dimension.

    Only methods whose name equals *attrname* or starts with `attrname + "_"`
    are expanded (this keeps methods from other `test*` functions untouched
    when multiple test methods coexist in the same `newattrs` dict).

    For each matching method and each enabled value in *variant*, a new
    wrapper method is created with the value name appended
    (`method_name + "_" + value_name`).  The wrapper delegates to the original
    method, carries the variant attribute, and is optionally wrapped with
    `unittest.expectedFailure` or `unittest.skip` based on predicates
    found in *xfail_fns* / *skip_fns*.

    Args:
        attrname: The original test method name being processed by the
            metaclass (e.g. `"test_foo"`).
        methods: `dict[str, callable]` of accumulated methods (`newattrs`).
        variant: The `TestVariant` to expand along.
        xfail_fns: `__variant_xfail__` dict from the original test method.
        skip_fns: `__variant_skip__` dict from the original test method.

    Returns:
        A new dict with the original matching methods replaced by their
        per-value copies.  Non-matching entries are passed through.
    """
    no_reason = lambda *args, **kwargs: None
    xfail_fn = xfail_fns.get(variant.name, no_reason)
    skip_fn = skip_fns.get(variant.name, no_reason)
    expanded = {}
    for method_name, method in methods.items():
        if not method_name.startswith("test"):
            expanded[method_name] = method
            continue
        if method_name != attrname and not method_name.startswith(attrname + "_"):
            expanded[method_name] = method
            continue
        for value_name in variant.get_enabled_values():
            if _is_excluded_variant_combination(method, variant.name, value_name):
                continue
            new_name = method_name + "_" + value_name

            @decorators.add_test_categories([value_name])
            @wraps(method)
            def variant_method(self, method=method):
                return method(self)

            variant_method.__name__ = new_name
            setattr(variant_method, variant.name, value_name)

            for attr in variant.attrs_to_preserve:
                if hasattr(method, attr):
                    setattr(variant_method, attr, getattr(method, attr))

            xfail_reason = xfail_fn(**{variant.name: value_name})
            if xfail_reason:
                variant_method = unittest.expectedFailure(variant_method)

            skip_reason = skip_fn(**{variant.name: value_name})
            if skip_reason:
                variant_method = unittest.skip(skip_reason)(variant_method)

            expanded[new_name] = variant_method
    return expanded


_test_variants = []
# Variant value combinations that should never be generated. Each entry maps
# `variant_name -> value`; a method copy is dropped when its already-set
# variant attributes plus the new value being added match every key in the
# entry. Add entries here for crosses that don't exercise anything new and
# would only inflate the matrix on remote test runs.
_excluded_variant_combinations = [
    # Example (uncomment + adapt when registering a real cross to drop):
    # {"swift_module_importer": "noclang", "swift_embedded": "swiftembed"},
]


def _is_excluded_variant_combination(method, variant_name, value_name):
    """Return True if assigning *variant_name=value_name* to *method* would
    produce a combination listed in `_excluded_variant_combinations`."""
    for combo in _excluded_variant_combinations:
        if combo.get(variant_name) != value_name:
            continue
        if all(
            getattr(method, k, None) == v for k, v in combo.items() if k != variant_name
        ):
            return True
    return False


class LLDBTestCaseFactory(type):
    def __new__(cls, name, bases, attrs):
        original_testcase = super(LLDBTestCaseFactory, cls).__new__(
            cls, name, bases, attrs
        )

        # Check if any test methods need variant expansion
        has_variant_tests = any(
            attrname.startswith("test")
            and any(v.should_expand(attrvalue) for v in _test_variants)
            for attrname, attrvalue in attrs.items()
        )

        if (
            hasattr(original_testcase, "NO_DEBUG_INFO_TESTCASE")
            and original_testcase.NO_DEBUG_INFO_TESTCASE  # type: ignore
            and not has_variant_tests
        ):
            return original_testcase

        # Default implementation for skip/xfail reason based on the debug category,
        # where "None" means to run the test as usual.
        def no_reason(*args, **kwargs):
            return None

        debug_info_categories = {
            "dwarf": True,
            "dwo": True,
            "dsym": True,
            "pdb": False,
            "gmodules": False,
        }

        newattrs = {}
        for attrname, attrvalue in attrs.items():
            if attrname.startswith("test") and not getattr(
                attrvalue, "__no_debug_info_test__", False
            ):
                # Track only the entries created by THIS attrname so that
                # variant expansion doesn't accidentally double-expand entries
                # from a sibling test method whose name happens to be a strict
                # prefix of attrname (e.g. test_foo vs test_foo_bar).
                this_attr_entries = {}
                # Create debug info variants unless NO_DEBUG_INFO_TESTCASE
                if not original_testcase.NO_DEBUG_INFO_TESTCASE:  # type: ignore
                    # If any debug info categories were explicitly tagged, assume that list to be
                    # authoritative.  If none were specified, try with all debug info formats.
                    test_method_categories = set(getattr(attrvalue, "categories", []))
                    all_dbginfo_categories = set(debug_info_categories.keys())
                    dbginfo_categories = test_method_categories & all_dbginfo_categories
                    other_categories = list(
                        test_method_categories - all_dbginfo_categories
                    )
                    if not dbginfo_categories:
                        dbginfo_categories = {
                            category
                            for category, enabled in debug_info_categories.items()
                            if enabled
                        }

                    # PDB is off by default, because it has a lot of failures right now.
                    # See llvm.org/pr149498
                    if original_testcase.TEST_WITH_PDB_DEBUG_INFO:  # type: ignore
                        dbginfo_categories.add("pdb")

                    xfail_fns = getattr(attrvalue, "__variant_xfail__", {})
                    skip_fns = getattr(attrvalue, "__variant_skip__", {})
                    xfail_for_debug_info_cat_fn = xfail_fns.get("debug_info", no_reason)
                    skip_for_debug_info_cat_fn = skip_fns.get("debug_info", no_reason)
                    for cat in dbginfo_categories:

                        @decorators.add_test_categories([cat])
                        @wraps(attrvalue)
                        def test_method(self, attrvalue=attrvalue):
                            return attrvalue(self)

                        method_name = attrname + "_" + cat
                        test_method.__name__ = method_name
                        test_method.debug_info = cat  # type: ignore
                        test_method.categories = other_categories + [cat]  # type: ignore

                        xfail_reason = xfail_for_debug_info_cat_fn(debug_info=cat)
                        if xfail_reason:
                            test_method = unittest.expectedFailure(test_method)

                        skip_reason = skip_for_debug_info_cat_fn(debug_info=cat)
                        if skip_reason:
                            test_method = unittest.skip(skip_reason)(test_method)

                        this_attr_entries[method_name] = test_method
                else:
                    # NO_DEBUG_INFO_TESTCASE — put method in this_attr_entries
                    # for variant expansion.
                    this_attr_entries[attrname] = attrvalue

                # Expand test variants only on the entries we just created
                # for this attrname, not on the whole newattrs dict (which
                # would double-expand sibling methods whose names share a
                # prefix).
                for variant in _test_variants:
                    if variant.should_expand(attrvalue):
                        xfail_fns = getattr(attrvalue, "__variant_xfail__", {})
                        skip_fns = getattr(attrvalue, "__variant_skip__", {})
                        this_attr_entries = _expand_test_variants(
                            attrname,
                            this_attr_entries,
                            variant,
                            xfail_fns=xfail_fns,
                            skip_fns=skip_fns,
                        )

                # Merge this attrname's variant-expanded entries into
                # newattrs.
                newattrs.update(this_attr_entries)

            else:
                newattrs[attrname] = attrvalue

        if original_testcase.TEST_WITH_PDB_DEBUG_INFO:  # type: ignore
            newattrs["SHARED_BUILD_TESTCASE"] = False

        return super(LLDBTestCaseFactory, cls).__new__(cls, name, bases, newattrs)
