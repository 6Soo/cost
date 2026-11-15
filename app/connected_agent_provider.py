"""Shared bounded-subprocess helpers for the P2 providers.

The opencode free-model agent that lived here was removed; P2 runs through
frontier_agent_provider and tools/p2_batch. Only the process boundary, the
AgentUnavailable error and the enable/cap config readers remain.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import threading

MAX_OUTPUT_BYTES = 512 * 1024


class AgentUnavailable(Exception):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


def enabled(config_path):
    try:
        options = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        return options.get('autonomous_ai_review') is True
    except FileNotFoundError:
        return os.environ.get('WEBLEDGER_AUTONOMOUS_AI_REVIEW') == '1'
    except (OSError, ValueError, AttributeError):
        return False


def daily_cap(config_path):
    try:
        options = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        cap = options.get('autonomous_ai_review_daily_cap')
        return cap if isinstance(cap, int) and cap >= 0 else 200
    except (OSError, ValueError, AttributeError):
        return 200

def _owned_job(process):
    """Own descendants for cleanup even when their parent exits first (Windows)."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes as wt
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wt.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                    ('active_limit', wt.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', wt.DWORD), ('scheduling', wt.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [wt.LPVOID, wt.LPCWSTR], wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: lifecycle, not sandbox.
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        if handle:
            kernel.CloseHandle(handle)
        process.kill()
        process.wait()
        raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
    if not kernel.AssignProcessToJobObject(handle, wt.HANDLE(int(process._handle))):
        kernel.CloseHandle(handle)
        process.kill()
        process.wait()
        raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
    return lambda: kernel.CloseHandle(handle)


def _resume_owned_process(process):
    """Resume only our suspended primary thread, after its Job is assigned."""
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes as wt
    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', wt.DWORD), ('usage', wt.DWORD), ('thread_id', wt.DWORD),
                    ('owner_pid', wt.DWORD), ('base_priority', wt.LONG),
                    ('delta_priority', wt.LONG), ('flags', wt.DWORD)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes, kernel.CreateToolhelp32Snapshot.restype = [wt.DWORD, wt.DWORD], wt.HANDLE
    kernel.Thread32First.argtypes = kernel.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.OpenThread.argtypes, kernel.OpenThread.restype = [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE
    kernel.ResumeThread.argtypes, kernel.ResumeThread.restype = [wt.HANDLE], wt.DWORD
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.owner_pid == process.pid:
                handle = kernel.OpenThread(2, False, entry.thread_id)  # THREAD_SUSPEND_RESUME
                if not handle:
                    raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
                try:
                    if kernel.ResumeThread(handle) == 0xFFFFFFFF:
                        raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
                    return
                finally:
                    kernel.CloseHandle(handle)
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
    finally:
        kernel.CloseHandle(snapshot)


# Scoped to the calling worker thread; child-output reader threads do not use it.
from contextvars import ContextVar
_process_check = ContextVar('p2_process_check', default=None)


def _run_bounded(command, *, cwd, env, timeout, input_bytes=None, check=None):
    process = subprocess.Popen(command, executable=command[0], cwd=cwd, env=env,
                               stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                                              | (4 if os.name == 'nt' else 0)))  # CREATE_SUSPENDED
    close_job = _owned_job(process)
    try:
        _resume_owned_process(process)
    except BaseException:
        if close_job:
            close_job()
        process.kill()
        process.wait()
        raise
    chunks, size, exceeded = [[], []], [0], threading.Event()
    mutex = threading.Lock()

    def read(pipe, index):
        try:
            while block := pipe.read(8192):
                with mutex:
                    size[0] += len(block)
                    if size[0] > MAX_OUTPUT_BYTES:
                        exceeded.set()
                    else:
                        chunks[index].append(block)
        finally:
            pipe.close()

    def write():
        try:
            process.stdin.write(input_bytes)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            process.stdin.close()

    threads = [threading.Thread(target=read, args=(process.stdout, 0), daemon=True),
               threading.Thread(target=read, args=(process.stderr, 1), daemon=True)]
    if input_bytes is not None:
        threads.append(threading.Thread(target=write, daemon=True))
    for thread in threads:
        thread.start()
    started = time.monotonic()
    try:
        while process.poll() is None:
            callback = check or _process_check.get()
            if callback is not None:
                callback()
            if exceeded.wait(.02):
                raise AgentUnavailable('AGENT_RESPONSE_TOO_LARGE')
            if time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(command, timeout)
        for thread in threads:
            thread.join(timeout=max(.1, timeout - (time.monotonic() - started)))
        if any(thread.is_alive() for thread in threads):
            raise subprocess.TimeoutExpired(command, timeout)
        if exceeded.is_set():
            raise AgentUnavailable('AGENT_RESPONSE_TOO_LARGE')
        return subprocess.CompletedProcess(command, process.returncode, b''.join(chunks[0]), b''.join(chunks[1]))
    except BaseException:
        if close_job:
            close_job()
            close_job = None
        elif os.name == 'nt' and process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            process.kill()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    finally:
        if close_job:
            close_job()
