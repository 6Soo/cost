"""The host's background jobs run in one worker process, from the release it was deployed with."""
import json
import os
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import webledger_worker as worker  # noqa: E402


def _config(tmp_path, jobs):
    path = tmp_path / "worker.json"
    path.write_text(json.dumps({"log": str(tmp_path / "worker.log"), "jobs": jobs}), encoding="utf-8")
    return path


def test_release_arguments_point_into_this_release_and_others_pass_unchanged():
    assert worker._resolve("release:ledger/master_ledger.csv") == str(worker.ROOT / "ledger" / "master_ledger.csv")
    for value in ("--watch", "D:/WebLedgerHost/config/x.json", "https://example.com/a/b", "app.mail_collect"):
        assert worker._resolve(value) == value


@pytest.mark.parametrize("job", [
    {"name": "a", "kind": "shell"},
    {"name": "a", "kind": "watch"},
    {"name": "a", "kind": "process", "python": "py", "every_seconds": 60, "timeout_seconds": 10},
])
def test_an_incomplete_job_is_refused(tmp_path, job):
    with pytest.raises(ValueError, match="WORKER_JOB_INVALID"):
        worker.load_config(_config(tmp_path, [job]))


def test_two_jobs_with_one_name_are_refused(tmp_path):
    job = {"name": "a", "kind": "watch", "module": "m", "argv": []}
    with pytest.raises(ValueError):
        worker.load_config(_config(tmp_path, [job, job]))


def test_restart_backs_off_and_is_capped():
    assert [worker.restart_delay(n) for n in (1, 2, 3)] == [60, 120, 240]
    assert worker.restart_delay(20) == worker.RESTART_CAP_SECONDS


def test_a_watch_job_that_fails_is_started_again_without_stopping(tmp_path, monkeypatch):
    calls = []
    module = types.ModuleType("fake_watch_tool")

    def main(argv):
        calls.append(argv)
        if len(calls) == 1:
            raise RuntimeError("source unavailable")
        return 0

    module.main = main
    monkeypatch.setitem(sys.modules, "fake_watch_tool", module)
    stop, waits = threading.Event(), []

    def sleep(seconds):
        waits.append(seconds)
        if len(calls) == 2:
            stop.set()

    log = worker.Log(tmp_path / "worker.log")
    worker.run_watch({"name": "w", "module": "fake_watch_tool", "argv": ["--watch", "release:x/y"]},
                     log, stop, sleep=sleep)
    assert calls == [["--watch", str(worker.ROOT / "x" / "y")]] * 2
    assert waits == [60, 120]
    log.flush()
    events = [json.loads(line)["event"] for line in (tmp_path / "worker.log").read_text(encoding="utf-8").splitlines()]
    assert events == ["start", "error", "start", "exit"]


def _process_job(tmp_path, code, **overrides):
    script = tmp_path / "tool.py"
    script.write_text(code, encoding="utf-8")
    return {"name": "p", "kind": "process", "python": sys.executable, "argv": [str(script)],
            "every_seconds": 3600, "timeout_seconds": 30, "log": str(tmp_path / "p.log"), **overrides}


def test_a_process_job_runs_once_per_period_and_keeps_its_output(tmp_path):
    stop, waits = threading.Event(), []
    job = _process_job(tmp_path, "print('collected')")

    def wait(seconds):
        waits.append(seconds)
        stop.set()

    log = worker.Log(tmp_path / "worker.log")
    worker.run_process(job, log, stop, wait=wait)
    assert "collected" in (tmp_path / "p.log").read_text(encoding="utf-8")
    assert 3500 < waits[0] <= 3600
    log.flush()
    exits = [json.loads(line) for line in (tmp_path / "worker.log").read_text(encoding="utf-8").splitlines()]
    assert exits[-1]["event"] == "exit" and exits[-1]["code"] == 0


def test_a_process_job_past_its_timeout_is_stopped(tmp_path):
    stop = threading.Event()
    job = _process_job(tmp_path, "import time; time.sleep(60)", timeout_seconds=1)
    log = worker.Log(tmp_path / "worker.log")
    worker.run_process(job, log, stop, wait=lambda seconds: stop.set())
    log.flush()
    last = json.loads((tmp_path / "worker.log").read_text(encoding="utf-8").splitlines()[-1])
    assert last["event"] == "timeout"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_stopping_the_worker_stops_the_job_it_started(tmp_path):
    import subprocess
    import time

    pid_file = tmp_path / "child.pid"
    tool = tmp_path / "tool.py"
    tool.write_text(f"import os, time; open(r'{pid_file}', 'w').write(str(os.getpid())); time.sleep(120)",
                    encoding="utf-8")
    config = tmp_path / "worker.json"
    config.write_text(json.dumps({"log": str(tmp_path / "worker.log"), "jobs": [
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
        alive = subprocess.run(["tasklist", "/FI", f"PID eq {child}", "/NH"], capture_output=True, text=True).stdout
        if str(child) not in alive:
            return
        time.sleep(0.2)
    raise AssertionError("the job outlived the worker")


def test_a_second_worker_is_refused_while_one_runs(tmp_path):
    import subprocess
    import time

    config = tmp_path / "worker.json"
    config.write_text(json.dumps({"log": str(tmp_path / "worker.log"), "jobs": [
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
