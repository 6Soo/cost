"""Focused real-process checks for the WebLedger Windows lifetime helper."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.webledger_windows_lifecycle import mutex_name


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "webledger_windows_lifecycle.py"


def launch(port, code, role="Board"):
    return subprocess.Popen(
        [sys.executable, str(HELPER), "--role", role, "--port", str(port), "--",
         sys.executable, "-c", code],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def wait_for(process, timeout=8):
    return process.wait(timeout=timeout)


def test_mutex_is_port_scoped_for_intentional_blue_green_overlap():
    assert mutex_name(8751).endswith(".8751")
    assert mutex_name(8751) != mutex_name(8752)
    code = "import time; time.sleep(1)"
    first = launch(18751, code)
    time.sleep(.25)  # allow the suspended creator to publish its mutex
    second = launch(18751, code)
    prepared = launch(18752, code, role="Prepared")
    try:
        assert wait_for(second) == 75
        assert wait_for(first) == 0
        assert wait_for(prepared) == 0
    finally:
        for process in (first, second, prepared):
            if process.poll() is None:
                process.kill()


def test_parent_stop_cleans_descendant_tree():
    child_code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
    parent = launch(18751, child_code)
    try:
        time.sleep(.5)
        parent.kill()
        parent.wait(timeout=5)
        time.sleep(.5)
        probe = launch(18751, "pass")
        assert wait_for(probe) == 0
    finally:
        if parent.poll() is None:
            parent.kill()


def test_child_crash_and_restart_releases_mutex():
    crashed = launch(18752, "raise SystemExit(23)")
    assert wait_for(crashed) == 23
    restarted = launch(18752, "pass")
    assert wait_for(restarted) == 0


def test_stop_cleanup_is_repeatable():
    for port in (18753, 18754, 18755):
        worker = launch(port, "import time; time.sleep(60)")
        try:
            time.sleep(.2)
            worker.kill()
            worker.wait(timeout=5)
        finally:
            if worker.poll() is None:
                worker.kill()
        assert wait_for(launch(port, "pass")) == 0
