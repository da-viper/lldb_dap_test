"""Module for supporting unit testing of the lldb-server debug monitor exe.
"""

import os
import os.path
from pathlib import Path
import platform
import sys
from lldbsuite.test import configuration
import shutil
import select
import random


def _get_support_exe(basename):
    support_dir = Path(configuration.lldbDAPExec).parent

    return shutil.which(basename, path=support_dir)


def get_lldb_server_exe():
    """Return the lldb-server exe path.

    Returns:
        A path to the lldb-server exe if it is found to exist; otherwise,
        returns None.
    """

    return _get_support_exe("lldb-server")


def get_debugserver_exe():
    """Return the debugserver exe path.

    Returns:
        A path to the debugserver exe if it is found to exist; otherwise,
        returns None.
    """
    if (
        configuration.arch
        and configuration.arch == "x86_64"
        and platform.machine().startswith("arm64")
    ):
        return "/Library/Apple/usr/libexec/oah/debugserver"

    return _get_support_exe("debugserver")


# A class representing a pipe for communicating with debug server.
# This class includes menthods to open the pipe and read the port number from it.
if sys.platform == "windows":
    import ctypes
    import ctypes.wintypes
    from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR, LPDWORD, LPVOID

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    PIPE_ACCESS_INBOUND = 1
    FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
    FILE_FLAG_OVERLAPPED = 0x40000000
    PIPE_TYPE_BYTE = 0
    PIPE_REJECT_REMOTE_CLIENTS = 8
    INVALID_HANDLE_VALUE = -1
    ERROR_ACCESS_DENIED = 5
    ERROR_IO_PENDING = 997

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", LPVOID),
            ("InternalHigh", LPVOID),
            ("Offset", DWORD),
            ("OffsetHigh", DWORD),
            ("hEvent", HANDLE),
        ]

        def __init__(self):
            super(OVERLAPPED, self).__init__(
                Internal=0, InternalHigh=0, Offset=0, OffsetHigh=0, hEvent=None
            )

    LPOVERLAPPED = ctypes.POINTER(OVERLAPPED)

    CreateNamedPipe = kernel32.CreateNamedPipeW
    CreateNamedPipe.restype = HANDLE
    CreateNamedPipe.argtypes = (
        LPCWSTR,
        DWORD,
        DWORD,
        DWORD,
        DWORD,
        DWORD,
        DWORD,
        LPVOID,
    )

    ConnectNamedPipe = kernel32.ConnectNamedPipe
    ConnectNamedPipe.restype = BOOL
    ConnectNamedPipe.argtypes = (HANDLE, LPOVERLAPPED)

    CreateEvent = kernel32.CreateEventW
    CreateEvent.restype = HANDLE
    CreateEvent.argtypes = (LPVOID, BOOL, BOOL, LPCWSTR)

    GetOverlappedResultEx = kernel32.GetOverlappedResultEx
    GetOverlappedResultEx.restype = BOOL
    GetOverlappedResultEx.argtypes = (HANDLE, LPOVERLAPPED, LPDWORD, DWORD, BOOL)

    ReadFile = kernel32.ReadFile
    ReadFile.restype = BOOL
    ReadFile.argtypes = (HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED)

    CloseHandle = kernel32.CloseHandle
    CloseHandle.restype = BOOL
    CloseHandle.argtypes = (HANDLE,)

    class Pipe(object):
        def __init__(self, prefix):
            while True:
                self.name = "lldb-" + str(random.randrange(10**10))
                full_name = "\\\\.\\pipe\\" + self.name
                self._handle = CreateNamedPipe(
                    full_name,
                    PIPE_ACCESS_INBOUND
                    | FILE_FLAG_FIRST_PIPE_INSTANCE
                    | FILE_FLAG_OVERLAPPED,
                    PIPE_TYPE_BYTE | PIPE_REJECT_REMOTE_CLIENTS,
                    1,
                    4096,
                    4096,
                    0,
                    None,
                )
                if self._handle != INVALID_HANDLE_VALUE:
                    break
                if ctypes.get_last_error() != ERROR_ACCESS_DENIED:
                    raise ctypes.WinError(ctypes.get_last_error())

            self._overlapped = OVERLAPPED()
            self._overlapped.hEvent = CreateEvent(None, True, False, None)
            result = ConnectNamedPipe(self._handle, self._overlapped)
            assert result == 0
            if ctypes.get_last_error() != ERROR_IO_PENDING:
                raise ctypes.WinError(ctypes.get_last_error())

        def finish_connection(self, timeout):
            if not GetOverlappedResultEx(
                self._handle,
                self._overlapped,
                ctypes.byref(DWORD(0)),
                timeout * 1000,
                True,
            ):
                raise ctypes.WinError(ctypes.get_last_error())

        def read(self, size, timeout):
            buf = ctypes.create_string_buffer(size)
            if not ReadFile(
                self._handle, ctypes.byref(buf), size, None, self._overlapped
            ):
                if ctypes.get_last_error() != ERROR_IO_PENDING:
                    raise ctypes.WinError(ctypes.get_last_error())
            read = DWORD(0)
            if not GetOverlappedResultEx(
                self._handle, self._overlapped, ctypes.byref(read), timeout * 1000, True
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return buf.raw[0 : read.value]

        def close(self):
            CloseHandle(self._overlapped.hEvent)
            CloseHandle(self._handle)

else:

    class Pipe(object):
        def __init__(self, prefix):
            self.name = os.path.join(prefix, "stub_port_number")
            os.mkfifo(self.name)
            self._fd = os.open(self.name, os.O_RDONLY | os.O_NONBLOCK)

        def finish_connection(self, timeout):
            pass

        def read(self, size, timeout):
            (readers, _, _) = select.select([self._fd], [], [], timeout)
            if self._fd not in readers:
                raise TimeoutError
            return os.read(self._fd, size)

        def close(self):
            os.close(self._fd)
            os.unlink(self.name)
