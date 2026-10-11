"""Single-run lock and failure backoff for the Google authority sync. Never schedules anything itself.

The lock is an OS file lock, so two runs cannot hold it at once and a dead run releases it. The state file
records the last success, the last error code and the next time a retry is allowed, so repeated
failures wait longer instead of hammering Google every hour.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

BACKOFF_BASE = dt.timedelta(minutes=5)
BACKOFF_CAP = dt.timedelta(hours=1)


class LockHeld(Exception):
    pass


class StateError(Exception):
    """A retry state cannot safely govern whether another source read is allowed."""


def _try_lock(handle) -> None:
    """OS file lock. The OS drops it when the process dies, so nothing has to be taken over by time."""
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SyncLock:
    """Held for the life of the with-block. A live run is never taken over, and release never deletes the file."""

    def __init__(self, path, *, now: dt.datetime):
        self.path = Path(path)
        self.now = now
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            _try_lock(handle)
        except OSError:
            handle.close()
            raise LockHeld("SYNC_ALREADY_RUNNING") from None
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"started_at": self.now.isoformat(), "pid": os.getpid()}))
        handle.flush()
        self._handle = handle
        return self

    def __exit__(self, *exc):
        try:
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.flush()
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None
        return False


def read_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"consecutive_failures": 0, "last_ok_at": None, "last_error": None, "next_attempt_at": None}
    except (OSError, ValueError):
        raise StateError('SYNC_STATE_UNAVAILABLE') from None
    try:
        if not isinstance(state, dict) or not {'consecutive_failures', 'last_ok_at', 'last_error', 'next_attempt_at'} <= state.keys():
            raise ValueError
        failures = state['consecutive_failures']
        if type(failures) is not int or failures < 0:
            raise ValueError
        if state['last_error'] is not None and not isinstance(state['last_error'], str):
            raise ValueError
        for key in ('last_ok_at', 'next_attempt_at'):
            if state[key] is not None:
                stamp = dt.datetime.fromisoformat(state[key])
                if stamp.utcoffset() is None:
                    raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise StateError('SYNC_STATE_UNAVAILABLE') from None
    return state


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
        # Bound the exponent before timedelta multiplication, even after a long outage.
        exponent = min(failures - 1, (BACKOFF_CAP // BACKOFF_BASE).bit_length())
        wait = min(BACKOFF_BASE * (2 ** exponent), BACKOFF_CAP)
        state = {**state, "consecutive_failures": failures, "last_error": error_code,
                 "next_attempt_at": (now + wait).isoformat()}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return state
