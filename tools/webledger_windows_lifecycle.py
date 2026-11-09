"""Windows lifetime primitives for the WebLedger host.

The scheduled task owns one supervisor.  This module is the source controlled
equivalent of the temporary board wrapper: a process is created suspended,
assigned to a kill-on-job-close job, and only then resumed.  A mutex is scoped
to the loopback port, so an intentional blue/green pair can use 8751 and 8752
while two supervisors for one port cannot race into bind().
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import datetime
import os
from pathlib import Path
import subprocess
from typing import Sequence


ERROR_ALREADY_EXISTS = 183
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
LOG_LIMIT_BYTES = 2 * 1024 * 1024
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


def _kernel():
    if os.name != "nt":
        raise OSError("WEBLEDGER_WINDOWS_LIFECYCLE_REQUIRES_WINDOWS")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                wintypes.LPVOID, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID,
                                      wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.LPCWSTR,
                                      ctypes.POINTER(_StartupInfo),
                                      ctypes.POINTER(_ProcessInformation)]
    kernel.CreateProcessW.restype = wintypes.BOOL
    return kernel


def mutex_name(port: int) -> str:
    if not 1 <= port <= 65535:
        raise ValueError("PORT_INVALID")
    return rf"Local\AX.WebLedger.Board.{port}"


def _environment_block(env: dict[str, str]) -> ctypes.Array:
    return ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(env.items())) + "\0\0")


def _open_log(path: str | os.PathLike[str]):
    """The child's console output, appended to `path` and rotated once past the size limit."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > LOG_LIMIT_BYTES:
        target.replace(target.with_suffix(".previous.log"))
    stream = target.open("ab", buffering=0)
    stream.write(f"\nSTART {datetime.datetime.now().astimezone().isoformat()}\n".encode("utf-8"))
    return stream


def run_owned(command: Sequence[str], *, port: int, role: str,
              cwd: str | os.PathLike[str] | None = None,
              env: dict[str, str] | None = None,
              log: str | os.PathLike[str] | None = None) -> int:
    """Run one logical worker with fail-closed mutex and Job ownership.

    With `log`, the child gets no console and writes its output there, which is what the separate
    hidden-console wrapper used to do as an extra process.
    """
    if role not in {"Board", "Prepared"}:
        raise ValueError("ROLE_INVALID")
    kernel = _kernel()
    mutex = kernel.CreateMutexW(None, False, mutex_name(port))
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel.CloseHandle(mutex)
        return 75

    job = kernel.CreateJobObjectW(None, None)
    process_info = _ProcessInformation()
    stream = null_input = None
    try:
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _JobLimits()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                              ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())

        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT
        if log is not None:
            import msvcrt

            stream = _open_log(log)
            null_input = open(os.devnull, "rb")
            output, empty = msvcrt.get_osfhandle(stream.fileno()), msvcrt.get_osfhandle(null_input.fileno())
            os.set_handle_inheritable(output, True)
            os.set_handle_inheritable(empty, True)
            startup.dwFlags = STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = empty, output, output
            flags |= CREATE_NO_WINDOW
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(command)))
        merged = os.environ.copy()
        if env:
            merged.update(env)
        env_block = _environment_block(merged)
        ok = kernel.CreateProcessW(None, command_line, None, None, log is not None, flags,
                                   env_block, os.fspath(cwd) if cwd else None,
                                   ctypes.byref(startup), ctypes.byref(process_info))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(job, process_info.hProcess):
            error = ctypes.get_last_error()
            kernel.TerminateProcess(process_info.hProcess, 1)
            raise ctypes.WinError(error)
        if kernel.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.WaitForSingleObject(process_info.hProcess, INFINITE) != WAIT_OBJECT_0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(process_info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if stream is not None:
            stream.write(f"EXIT {int(code.value)}\n".encode("ascii"))
        return int(code.value)
    finally:
        if stream is not None:
            stream.close()
        if null_input is not None:
            null_input.close()
        if process_info.hThread:
            kernel.CloseHandle(process_info.hThread)
        if process_info.hProcess:
            kernel.CloseHandle(process_info.hProcess)
        if job:
            kernel.CloseHandle(job)
        kernel.CloseHandle(mutex)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("Board", "Prepared"), required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", help="Append the child's output here and give it no console.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command or args.command[0] != "--":
        parser.error("COMMAND_REQUIRED_AFTER_DOUBLE_DASH")
    return run_owned(args.command[1:], port=args.port, role=args.role, log=args.log)


if __name__ == "__main__":
    raise SystemExit(main())
