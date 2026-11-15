"""One process for the WebLedger host's background jobs.

Replaces the separate scheduled tasks that each kept their own interpreter (and, through the venv
launcher, a second one) alive: the participant roster watch, the review source watch, the hourly
mail collection and the hourly Google authority sync. Every job runs from this release, so a
deployment moves them together with the board.

* ``watch`` jobs call an existing tool's ``main(argv)`` in a thread, exactly as its own ``--watch``
  loop ran before. A job that stops is started again after a growing pause; the others carry on.
* ``process`` jobs start the tool as a child on a fixed period, with the interpreter it always
  used, and are stopped if they run past their timeout.

Configuration is a host file (paths and credentials belong to the host, not the release). An
argument written ``release:<path>`` names a file inside this release.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import importlib
import json
import os
import site
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTEX_NAME = r"Local\AX.WebLedger.Worker"
RESTART_SECONDS = 60
RESTART_CAP_SECONDS = 900
LOG_LIMIT_BYTES = 4 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000


def use_venv(venv: Path) -> None:
    """Put the venv's packages ahead of the base interpreter's, as running inside it would."""
    packages = venv / "Lib" / "site-packages"
    if not packages.is_dir():
        raise SystemExit("WORKER_VENV_MISSING")
    before = list(sys.path)
    site.addsitedir(str(packages))
    added = [entry for entry in sys.path if entry not in before]
    sys.path[:] = added + before


class Log:
    """One append-only log for the worker and its in-process jobs, rotated once at a size limit."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_LIMIT_BYTES:
            path.replace(path.with_suffix(".previous.log"))
        self.stream = path.open("a", encoding="utf-8", buffering=1)

    def write(self, text: str) -> int:
        with self.lock:
            return self.stream.write(text)

    def flush(self) -> None:
        with self.lock:
            self.stream.flush()

    def note(self, job: str, event: str, **fields) -> None:
        record = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                  "job": job, "event": event, **fields}
        self.write(json.dumps(record, ensure_ascii=False) + "\n")


RELEASE_PREFIX = "release:"


def _resolve(value: str) -> str:
    """`release:<path>` points into this release; every other argument is passed as written."""
    if not value.startswith(RELEASE_PREFIX):
        return value
    return str((ROOT / value[len(RELEASE_PREFIX):]).resolve())


def restart_delay(failures: int) -> float:
    return min(RESTART_SECONDS * 2 ** max(failures - 1, 0), RESTART_CAP_SECONDS)


def run_watch(job: dict, log: Log, stop: threading.Event, sleep=time.sleep) -> None:
    """Keep a tool's own watch loop running; a loop that ends or fails is started again."""
    name, failures = job["name"], 0
    while not stop.is_set():
        log.note(name, "start")
        started = time.monotonic()
        try:
            module = importlib.import_module(job["module"])
            code = module.main([_resolve(arg) for arg in job["argv"]])
            log.note(name, "exit", code=code)
        except SystemExit as exc:
            log.note(name, "exit", code=exc.code)
        except Exception as exc:  # noqa: BLE001 - one job must not stop the others
            log.note(name, "error", error=type(exc).__name__, message=str(exc)[:200])
        # A loop that ran for a while before ending starts its back-off again.
        failures = 1 if time.monotonic() - started > RESTART_CAP_SECONDS else failures + 1
        sleep(restart_delay(failures))


def child_command(job: dict) -> tuple[list[str], dict | None]:
    from app.python_launch import child_environment, python_command

    interpreter, extra = python_command(job["python"])
    return [*interpreter, *[_resolve(arg) for arg in job["argv"]]], child_environment(extra)


def run_process(job: dict, log: Log, stop: threading.Event, now=time.monotonic, wait=None) -> None:
    """Start the job every `every_seconds`, never two at once, and stop one that overruns."""
    name, every, timeout = job["name"], float(job["every_seconds"]), float(job["timeout_seconds"])
    wait = wait or stop.wait
    output = Path(job["log"])
    while not stop.is_set():
        started = now()
        command, env = child_command(job)
        log.note(name, "start")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with open(output, "ab") as stream:
                process = subprocess.Popen(command, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
                try:
                    code = process.wait(timeout=timeout)
                    log.note(name, "exit", code=code, seconds=round(now() - started, 1))
                except subprocess.TimeoutExpired:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    process.wait()
                    log.note(name, "timeout", seconds=timeout)
        except OSError as exc:
            log.note(name, "error", error=type(exc).__name__, message=str(exc)[:200])
        wait(max(every - (now() - started), 1.0))


def own_children() -> None:
    """Put this process in a kill-on-close Job: stopping the worker also stops what it started,
    so a deployment never leaves a collection from the previous release running beside the next."""
    if os.name != "nt":
        return
    from webledger_windows_lifecycle import (JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                             JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, _JobLimits, _kernel)

    kernel = _kernel()
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    job = kernel.CreateJobObjectW(None, None)
    limits = _JobLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (job and kernel.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                    ctypes.byref(limits), ctypes.sizeof(limits))
            and kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        raise ctypes.WinError(ctypes.get_last_error())
    own_children.job = job  # closed only when this process ends


def single_instance(name: str = MUTEX_NAME) -> bool:
    if os.name != "nt":
        return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, name)
    single_instance.handle = handle  # held for the life of the process
    return bool(handle) and ctypes.get_last_error() != 183


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    names = set()
    for job in config["jobs"]:
        if job["kind"] not in {"watch", "process"} or job["name"] in names:
            raise ValueError("WORKER_JOB_INVALID")
        names.add(job["name"])
        if job["kind"] == "process" and not all(job.get(key) for key in ("python", "every_seconds", "timeout_seconds", "log")):
            raise ValueError("WORKER_JOB_INVALID")
        if job["kind"] == "watch" and not job.get("module"):
            raise ValueError("WORKER_JOB_INVALID")
    return config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if config.get("venv"):
        use_venv(Path(config["venv"]))
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    # Same card-flow.json switches as the board launcher, so one writer serves every host process.
    from app import core_switch_config
    try:
        core_switch_config.apply_from_host(args.config.resolve().parent, args.config.resolve().parent.parent / "data")
    except core_switch_config.CoreSwitchRefused as exc:
        raise SystemExit(f"WORKER_{exc.code}")
    log = Log(Path(config["log"]))
    # Tools print their results; with pythonw there is no console to print to.
    sys.stdout = sys.stderr = log
    # A test or second host can name its own instance; the default is the host's one worker.
    if not single_instance(config.get("instance_name") or MUTEX_NAME):
        log.note("worker", "refused", reason="ALREADY_RUNNING")
        return 75
    own_children()
    log.note("worker", "ready", release=ROOT.name, jobs=[job["name"] for job in config["jobs"]])
    stop = threading.Event()
    threads = []
    for job in config["jobs"]:
        target = run_watch if job["kind"] == "watch" else run_process
        thread = threading.Thread(target=target, args=(job, log, stop), name=job["name"], daemon=True)
        thread.start()
        threads.append(thread)
    try:
        while any(thread.is_alive() for thread in threads):
            time.sleep(30)
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
