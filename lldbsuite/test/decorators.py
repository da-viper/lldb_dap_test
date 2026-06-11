import platform
import sys
from typing import Callable, List, TypeVar
import unittest

from lldbsuite.test import configuration

T = TypeVar("T")


class no_match:
    def __init__(self, item):
        self.item = item


def skipIfPlatform(oslist: List[str]):
    """Decorate the item to skip tests if running on one of the listed platforms."""
    # This decorator cannot be ported to `skipIf` yet because it is used on entire
    # classes, which `skipIf` explicitly forbids.
    oslist = [name.lower() for name in oslist]
    return unittest.skipIf(
        sys.platform.lower() in oslist, "skip on %s" % (", ".join(oslist))
    )


def expected_failure_platform(oslist: List[str]):
    """Decorate the item to skip tests if running on one of the listed platforms."""
    # This decorator cannot be ported to `skipIf` yet because it is used on entire
    # classes, which `skipIf` explicitly forbids.
    oslist = [name.lower() for name in oslist]
    if sys.platform.lower() in oslist:
        return unittest.expectedFailure

    def null_opt(func: Callable[..., T]):
        return func

    return null_opt


def skipIfNoSignals(func):
    """Decorate the item to skip tests on platforms without signal support."""
    return skipIfPlatform(["windows", "wasip1", "wasi"])(func)


def expectedFailureNetBSD(func: Callable[..., T], bugnumber=None):
    return expected_failure_platform(["netbsd"])(func)


def expectedFailureAll(oslist: List[str] = [], **kwargs):
    return expected_failure_platform(oslist)


def expectedFailureWindows(func: Callable[..., T]):
    return expected_failure_platform(["windows"])(func)


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
    return skipIfPlatform(["darwin"])


def skipif_linux():
    return skipIfPlatform(["linux"])


def skipIfWindows(func: Callable[..., T]):
    return skipIfPlatform(["windows", "cygwin"])(func)


def skipUnlessDarwin(func: Callable[..., T]):
    return skipUnlessPlatform(["darwin"])(func)


def skipIfDarwin(func: Callable[..., T]):
    return skipIfPlatform(["darwin"])(func)


def skipIfLinux(func: Callable[..., T]):
    return skipIfPlatform(["linux"])(func)


def no_debug_info_test(func: Callable[..., T]):
    return func


def skipUnlessUndefinedBehaviorSanitizer(func: Callable[..., T]):
    return func

def skipUnlessAddressSanitizer(func):
    return func


def skipIfNetBSD(func: Callable[..., T]):
    return skipIfPlatform(["netbsd"])(func)


def skipIfRemote(func: Callable[..., T]):
    return skipIfPlatform(["remote"])(func)


def skipIfAsan(func: Callable[..., T]):
    return skipIfPlatform(["asan"])(func)


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
    return skipIfPlatform(["wasi"])


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
    return skipIfPlatform(["skipif"])


def add_test_categories(cat: List[str]):
    """Add test categories to a TestCase method"""
    # cat = test_categories.validate(cat, True)

    def impl(func: Callable[..., T]):
        try:
            if hasattr(func, "categories"):
                cat.extend(func.categories)  # type: ignore
            setattr(func, "categories", cat)
        except AttributeError:
            raise Exception("Cannot assign categories to inline tests.")

        return func

    return impl
