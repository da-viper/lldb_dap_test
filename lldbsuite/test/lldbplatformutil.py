""" This module contains functions used by the test cases to hide the
architecture and/or the platform dependent nature of the tests. """

# System modules
import itertools
import json
import re
import subprocess
import sys
import os
from typing import Optional
from packaging import version
from urllib.parse import urlparse


class _PlatformContext:
    """Value object class which contains platform-specific options."""

    def __init__(
        self, shlib_environment_var, shlib_path_separator, shlib_prefix, shlib_extension
    ):
        self.shlib_environment_var = shlib_environment_var
        self.shlib_path_separator = shlib_path_separator
        self.shlib_prefix = shlib_prefix
        self.shlib_extension = shlib_extension

    def getFullLibName(self, base_name):
        return f"{self.shlib_prefix}{base_name}.{self.shlib_extension}"


def getHostPlatform():
    """Returns the host platform running the test suite."""
    return getPlatform()


def getPlatform():
    return sys.platform


def platformIsDarwin():
    return getPlatform() == "darwin"


def findBacktraceRecordingDylib():
    if not platformIsDarwin():
        return ""

    with os.popen("xcode-select -p") as output:
        xcode_developer_path = output.read().strip()
        mtc_dylib_path = "%s/usr/lib/libBacktraceRecording.dylib" % xcode_developer_path
        if os.path.isfile(mtc_dylib_path):
            return mtc_dylib_path

    return ""


def getDarwinOSTriples():
    return ["darwin"]


def createPlatformContext():
    if sys.platform == "darwin":
        return _PlatformContext("DYLD_LIBRARY_PATH", ":", "lib", "dylib")
    elif sys.platform in ("linux", "freebsd", "netbsd", "openbsd"):
        return _PlatformContext("LD_LIBRARY_PATH", ":", "lib", "so")
    else:
        return _PlatformContext("PATH", ";", "", "dll")
