"""Windows-only single-instance and Job Object worker boundaries.

Both tests need Windows: the first reads `tasklist`, and the second relies on the
named-mutex single-instance guard, which is a Win32 caller only
(`tools/webledger_worker.py::single_instance` returns True on every other platform).
A Linux run of either is not evidence, and a Linux skip fails the quality gate,
so they execute unchanged here in the windows-p2-descendant-boundary job.

The portable half of the former test file - including the timeout boundary that
`run_process` now proves on every platform - stays in tests/test_webledger_worker.py.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import webledger_worker as worker  # noqa: E402


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_stopping_the_worker_stops_the_job_it_started(tmp_path):
    import subprocess
    import time

    pid_file = tmp_path / "child.pid"
    tool = tmp_path / "tool.py"
    tool.write_text(f"import os, time; open(r'{pid_file}', 'w').write(str(os.getpid())); time.sleep(120)",
                    encoding="utf-8")
    config = tmp_path / "worker.json"
    config.write_text(json.dumps({"log": str(tmp_path / "worker.log"), "instance_name": r"Local\webledger-worker-test-" + tmp_path.name, "jobs": [
        {"name": "slow", "kind": "process", "python": sys.executable, "argv": [str(tool)],
         "every_seconds": 3600, "timeout_seconds": 600, "log": str(tmp_path / "slow.log")}]}), encoding="utf-8")
    owner = subprocess.Popen([sys.executable, str(worker.ROOT / "tools" / "webledger_worker.py"), "--config", str(config)])
    try:
        deadline = time.monotonic() + 30
        while not pid_file.exists() or not pid_file.read_text():
            assert time.monotonic() < deadline, "the job did not start"
            time.sleep(0.2)
        child = int(pid_file.read_text())
    finally:
        owner.kill()
        owner.wait(10)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        alive = subprocess.run(["tasklist", "/FI", f"PID eq {child}", "/NH"], capture_output=True, text=True, errors="replace").stdout
        if str(child) not in alive:
            return
        time.sleep(0.2)
    raise AssertionError("the job outlived the worker")


def test_a_second_worker_is_refused_while_one_runs(tmp_path):
    import subprocess
    import time

    config = tmp_path / "worker.json"
    config.write_text(json.dumps({"log": str(tmp_path / "worker.log"), "instance_name": r"Local\webledger-worker-test-" + tmp_path.name, "jobs": [
        {"name": "idle", "kind": "watch", "module": "time", "argv": []}]}), encoding="utf-8")
    first = subprocess.Popen([sys.executable, str(worker.ROOT / "tools" / "webledger_worker.py"), "--config", str(config)])
    try:
        deadline = time.monotonic() + 20
        while '"ready"' not in ((tmp_path / "worker.log").read_text(encoding="utf-8") if (tmp_path / "worker.log").exists() else ""):
            assert time.monotonic() < deadline
            time.sleep(0.2)
        second = subprocess.run([sys.executable, str(worker.ROOT / "tools" / "webledger_worker.py"), "--config", str(config)],
                                timeout=20)
        assert second.returncode == 75
    finally:
        first.kill()
        first.wait(10)
