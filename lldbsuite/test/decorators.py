import platform
import sys
from typing import Callable, List, TypeVar
import unittest

from lldb_dap import configuration

T = TypeVar("T")

class no_match:
    def __init__(self, item):
        self.item = item


def skipif_platform(oslist: List[str]):
    """Decorate the item to skip tests if running on one of the listed platforms."""
    # This decorator cannot be ported to `skipIf` yet because it is used on entire
    # classes, which `skipIf` explicitly forbids.
    oslist = [name.lower() for name in oslist]
    return unittest.skipIf(
        sys.platform.lower() in oslist, "skip on %s" % (", ".join(oslist))
    )

def expected_failure_platform(oslist: List[str], func: Callable[..., T]):

    """Decorate the item to skip tests if running on one of the listed platforms."""
    # This decorator cannot be ported to `skipIf` yet because it is used on entire
    # classes, which `skipIf` explicitly forbids.
    oslist = [name.lower() for name in oslist]
    if sys.platform.lower() in oslist:
        return unittest.expectedFailure(func)
    return func


def expectedFailureNetBSD(bugnumber=None):
    def do_func(func: Callable[..., T]):
        return expected_failure_platform(["netbsd"], func)
    return do_func

def expectedFailureWindows(func: Callable[..., T]):
    return expected_failure_platform(["windows"], func)


def skipUnlessPlatform(oslist: List[str]):
    """Decorate the item to skip tests if running on one of the listed platforms."""
    # This decorator cannot be ported to `skipIf` yet because it is used on entire
    # classes, which `skipIf` explicitly forbids.
    oslist = [name.lower() for name in oslist]
    return unittest.skipUnless(
        sys.platform.lower() in oslist, "skip unless %s" % (", ".join(oslist))
    )


def skipUnlessArch(arch: str, /):
    return unittest.skipUnless(
        platform.machine() == arch, f"skip unless arch is {arch}"
    )


def skipif_darwin():
    return skipif_platform(["darwin"])


def skipif_linux():
    return skipif_platform(["linux"])


def skipIfWindows(func: Callable[..., T]):
    return skipif_platform(["windows", "cygwin"])(func)


def skipUnlessDarwin(func: Callable[..., T]):
    return skipUnlessPlatform(["darwin"])(func)


def skipIfDarwin(func: Callable[..., T]):
    return skipif_platform(["darwin"])(func)


def skipIfLinux(func: Callable[..., T]):
    return skipif_platform(["linux"])(func)


def skipIfNetBSD(func: Callable[..., T]):
    return skipif_platform(["netbsd"])(func)


def skipIfRemote(func: Callable[..., T]):
    return skipif_platform(["remote"])(func)


def skipIfAsan(func: Callable[..., T]):
    return skipif_platform(["asan"])(func)


def skipIfBuildType(types: List[str]):
    """Skip tests if built in a specific CMAKE_BUILD_TYPE.

    Supported types include 'Release', 'RelWithDebInfo', 'Debug', 'MinSizeRel'.
    """
    types = [name.lower() for name in types]
    return unittest.skipIf(
        configuration.cmake_build_type is not None
        and configuration.cmake_build_type.lower() in types,
        "skip on {} build type(s)".format(", ".join(types)),
    )

def skipIfTargetDoesNotSupportSharedLibraries():
    """Skip tests that require shared library (dylib/so) support."""
    return skipif_platform(["wasi"])


def skipIf(
    bugnumber=None,
    oslist=None,
    hostoslist=None,
    compiler=None,
    compiler_version=None,
    archs=None,
    triple=None,
    debug_info=None,
    swig_version=None,
    py_version=None,
    macos_version=None,
    remote=None,
    dwarf_version=None,
    setting=None,
    asan=None,
):
    return skipif_platform(["skipif"])

def add_test_categories(cat: List[str]):
    """Add test categories to a TestCase method"""
    # cat = test_categories.validate(cat, True)

    def impl(func: Callable[..., T]):
        try:
            if hasattr(func, "categories"):
                cat.extend(func.categories) # type: ignore
            setattr(func, "categories", cat)
        except AttributeError:
            raise Exception("Cannot assign categories to inline tests.")

        return func

    return impl
