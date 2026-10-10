"""Single-run lock and failure backoff for the Google authority sync. Never schedules anything itself.

The lock file keeps two runs from reading and writing the same snapshot at once. A lock older
than STALE_AFTER is taken over, because a run that died leaves its lock behind. The state file
records the last success, the last error code and the next time a retry is allowed, so repeated
failures wait longer instead of hammering Google every hour.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

STALE_AFTER = dt.timedelta(minutes=30)
BACKOFF_BASE = dt.timedelta(minutes=5)
BACKOFF_CAP = dt.timedelta(hours=1)


class LockHeld(Exception):
    pass


class SyncLock:
    def __init__(self, path: Path, *, now: dt.datetime):
        self.path = path
        self.now = now

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            started = dt.datetime.fromisoformat(json.loads(self.path.read_text(encoding="utf-8"))["started_at"])
            if self.now - started < STALE_AFTER:
                raise LockHeld("SYNC_ALREADY_RUNNING")
            self.path.unlink()
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"started_at": self.now.isoformat(), "pid": os.getpid()}, handle)
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return False


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"consecutive_failures": 0, "last_ok_at": None, "last_error": None, "next_attempt_at": None}
    return json.loads(path.read_text(encoding="utf-8"))


def may_attempt(state: dict, now: dt.datetime) -> bool:
    if not state.get("next_attempt_at"):
        return True
    return now >= dt.datetime.fromisoformat(state["next_attempt_at"])


def record_result(path: Path, *, ok: bool, now: dt.datetime, error_code: str | None = None) -> dict:
    state = read_state(path)
    if ok:
        state = {"consecutive_failures": 0, "last_ok_at": now.isoformat(), "last_error": None,
                 "next_attempt_at": None}
    else:
        failures = state["consecutive_failures"] + 1
        wait = min(BACKOFF_BASE * (2 ** (failures - 1)), BACKOFF_CAP)
        state = {**state, "consecutive_failures": failures, "last_error": error_code,
                 "next_attempt_at": (now + wait).isoformat()}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return state
