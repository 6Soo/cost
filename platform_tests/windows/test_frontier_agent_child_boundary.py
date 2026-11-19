"""Windows-only P2 subprocess descendant lifecycle boundary.

This boundary needs Win32 Job Objects, so it cannot be decided on Linux: the
assertion inside is the evidence itself and must not be weakened into a skip.
It runs unchanged in the dedicated `windows-p2-descendant-boundary` job for
every pull request and every push to main.
"""
import os
import subprocess
import sys

import pytest


def test_windows_immediate_child_spawn_is_owned_and_killed_on_timeout(tmp_path):
    import ctypes
    import os
    from ctypes import wintypes as wt
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
