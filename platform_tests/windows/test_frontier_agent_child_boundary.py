"""Windows-only P2 subprocess descendant lifecycle boundary.

This test needs Windows Job Objects, so it cannot run on the Linux impact-checks
host. It runs on the dedicated `windows-p2-descendant-boundary` job
(runs-on: windows-2022), which executes for every pull request and every push to
main. Nothing here is skipped: a non-Windows host fails the assertion instead of
silently passing, and the boundary assertions are unchanged from the former copy
in tests/test_frontier_agent_provider.py.
"""
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes as wt

import pytest


def test_windows_immediate_child_spawn_is_owned_and_killed_on_timeout(tmp_path):
    from app.connected_agent_provider import _run_bounded
    assert os.name == 'nt', 'This boundary must be verified on Windows'
    identity = tmp_path / 'synthetic-child.pid'
    child = 'import time; time.sleep(30)'
    parent = ('import subprocess,sys,time,pathlib; '
              'p=subprocess.Popen([sys.executable,"-c",' + repr(child) + ']); '
              'pathlib.Path(' + repr(str(identity)) + ').write_text(str(p.pid)); time.sleep(30)')
    with pytest.raises(subprocess.TimeoutExpired):
        _run_bounded([sys.executable, '-c', parent], cwd=tmp_path, env=dict(os.environ), timeout=1.5)
    assert identity.is_file(), 'The parent must actually spawn a child before timeout'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE
    kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, int(identity.read_text()))
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 1000) == 0
        finally:
            kernel.CloseHandle(handle)
