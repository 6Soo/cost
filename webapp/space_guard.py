"""Refuse a write when the volume cannot hold it, and say why.

SPEC_REFINEMENT 19.3 asks for a specific order and a specific honesty when a
free-tier volume fills up:

* new file acceptance and new output generation are refused first, with a
  reason;
* an existing ledger, source or output is never deleted, and a refusal is never
  reported as a parse error;
* a row save is refused too when even the minimum headroom is gone, and it is
  never reported as a success;
* a file that has not been received is never recorded as a received one.

One module, one answer. `webapp.ops` reads these constants from here, so a
health line and a write path cannot disagree about what "enough space" means.

Three things this module is careful about, each of which was a real defect in
the first version:

**One choke point.** Every state-changing transaction in `LedgerStore` opens with
`BEGIN IMMEDIATE`. `reserve_write` is what those call, so a new write path cannot
quietly bypass the policy the way a per-method call site can.

**No fail-open.** An unreadable `disk_usage` used to be reported as
"can write". `ops.health_check` already treated an unreadable probe as a failed
check, so the health line said the volume was a problem while the guard let
writes straight through. Both now refuse, and the refusal says the number could
not be read rather than pretending to a number.

**No syscall storm, no silent overcommit.** A probe per write turns a busy
server into a `stat` storm, and concurrent writers each reading the same free
space can each conclude there is room for the same bytes. `reserve_write`
caches a measurement briefly when it is far from the threshold, always re-probes
near it, and tracks outstanding reservations per volume so two writers cannot
both spend the same free bytes.

Nothing here deletes anything. Refusing a write is the whole job.
"""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

# Headroom kept free on every write. A write that fits exactly leaves nothing for
# the journal, the temp file, or the next one.
MIN_FREE_BYTES = 1 * 1024 * 1024

# Free space below this, after the write's own need, is a warning while writes
# still succeed. 19.3 asks for a warning *before* the volume is full.
#
# This is the only definition. The first version had health compute
# `free - MIN_FREE_BYTES < WARN_FREE_BYTES` and the guard compute
# `free - needed_bytes < WARN_FREE_BYTES`, so the same volume warned at 11 MiB on
# one surface and 10 MiB on the other. Both call `state()` now.
WARN_FREE_BYTES = 10 * 1024 * 1024

# How long a measurement far from the threshold may be reused. Near the
# threshold the probe always runs, so a caching window can never let a write
# through a volume that filled up since the last look.
PROBE_TTL_SECONDS = 1.0

_LOCK = threading.Lock()
_last_probe: dict[str, tuple[int, float]] = {}
_outstanding: dict[str, int] = {}


class SpaceRefused(Exception):
    """A write was refused because the volume could not hold it."""

    def __init__(self, code: str, message: str, *, free, needed, path,
                 reason: str = "insufficient_space"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.free = free
        self.needed = needed
        self.path = str(path)
        self.reason = reason


def _validate_needed(needed_bytes) -> int:
    """A negative or non-integer need would make every volume look roomy.

    `True` is an int in Python, and a bool reaching this position means a caller
    passed a flag by mistake. Both are refused rather than coerced.
    """
    if isinstance(needed_bytes, bool) or not isinstance(needed_bytes, int):
        raise ValueError(
            f"needed_bytes must be an int, got {type(needed_bytes).__name__}")
    if needed_bytes < 0:
        raise ValueError(f"needed_bytes must not be negative, got {needed_bytes}")
    return needed_bytes


def _volume_key(path: Path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(Path(path).absolute())


def _existing_ancestor(path: Path) -> Path:
    """The nearest directory that exists, so an uncreated path still measures.

    `shutil.disk_usage` raises on a path that does not exist. A write to a
    not-yet-created file or directory is still a write to a volume, so the probe
    walks up instead of giving up.
    """
    candidate = path
    for _ in range(64):
        if candidate.exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def free_bytes(path) -> int | None:
    """Free bytes on the volume holding `path`, or None if it cannot be read."""
    try:
        return shutil.disk_usage(str(_existing_ancestor(Path(path)))).free
    except (OSError, ValueError):
        return None


def _cached_free(path: Path) -> tuple[int | None, bool]:
    """Free bytes, and whether the number came from the cache."""
    key = _volume_key(path)
    now = time.monotonic()
    with _LOCK:
        cached = _last_probe.get(key)
    measured = free_bytes(path)
    if measured is None:
        with _LOCK:
            _last_probe.pop(key, None)
        return None, False
    near_threshold = measured < WARN_FREE_BYTES + MIN_FREE_BYTES
    if cached and not near_threshold:
        previous, at = cached
        if now - at < PROBE_TTL_SECONDS:
            return previous, True
    with _LOCK:
        _last_probe[key] = (measured, now)
    return measured, False


def reset_probe_cache() -> None:
    """Forget every cached measurement. For tests and for a forced re-probe."""
    with _LOCK:
        _last_probe.clear()
        _outstanding.clear()


def state(path, *, needed_bytes: int = 0, use_cache: bool = True) -> dict:
    """What a write to `path` would find, as facts rather than a verdict.

    `can_write` is False when the free space cannot be read. That matches
    `ops.health_check`, which reports an unreadable probe as a failed check, and
    it is the only safe reading: a number nobody measured cannot promise room.
    """
    needed_bytes = _validate_needed(needed_bytes)
    path = Path(path)
    if use_cache:
        free, cached = _cached_free(path)
    else:
        free, cached = free_bytes(path), False

    reserved = 0
    with _LOCK:
        reserved = _outstanding.get(_volume_key(path), 0)

    if free is None:
        return {"free_bytes": None, "needed_bytes": needed_bytes,
                "reserved_bytes": reserved, "headroom_bytes": None,
                "can_write": False, "warn": False, "cached": cached,
                "reason": "space_unreadable",
                "note": "여유 공간을 읽지 못했어요. 확인되지 않은 숫자로 "
                        "쓰기를 진행하지 않습니다"}
    effective = free - reserved
    return {
        "free_bytes": free,
        "reserved_bytes": reserved,
        "needed_bytes": needed_bytes,
        "headroom_bytes": effective - needed_bytes - MIN_FREE_BYTES,
        "can_write": effective - needed_bytes >= MIN_FREE_BYTES,
        "warn": effective - needed_bytes < WARN_FREE_BYTES,
        "cached": cached,
        "reason": "",
        "note": "",
    }


def reserve(path, needed_bytes: int, *, code: str, what: str) -> dict:
    """Refuse the write unless `needed_bytes` plus the headroom fits.

    `what` names the thing being refused so the reason reads as an action for
    the operator rather than a number.
    """
    measured = state(path, needed_bytes=needed_bytes)
    if measured["can_write"]:
        return measured
    free = measured["free_bytes"]
    if free is None:
        detail = (f"남은 공간을 읽지 못했어요. 여유 공간 {MIN_FREE_BYTES:,} "
                  f"바이트를 확인할 수 없어 거절했습니다")
    else:
        detail = (f"필요 {needed_bytes:,} 바이트 + 여유 공간 "
                  f"{MIN_FREE_BYTES:,} 바이트인데 남은 게 {free:,} 바이트"
                  + (f" (이 프로세스에서 예약됨 "
                     f"{measured['reserved_bytes']:,} 바이트)"
                     if measured["reserved_bytes"] else "") + "입니다")
    raise SpaceRefused(
        code,
        f"{what} 공간이 부족해서 거절했어요. {detail}. "
        f"이미 저장된 장부·원천·출력은 지우지 않았습니다.",
        free=free, needed=needed_bytes, path=Path(path),
        reason=measured["reason"] or "insufficient_space")


class reservation:
    """Hold space for the duration of one write.

    Two writers that read the same free space would otherwise each conclude
    there is room and both commit, leaving the volume overcommitted. The
    reservation is subtracted from the next writer's view of the volume and
    released when the block ends, on the way out as well as on an exception.
    """

    def __init__(self, path, needed_bytes: int, *, code: str, what: str):
        self.path = Path(path)
        self.needed = _validate_needed(needed_bytes)
        self.code = code
        self.what = what
        self.key = _volume_key(self.path)
        self.measured = None
        self._held = False

    def __enter__(self):
        self.measured = reserve(self.path, self.needed, code=self.code,
                                what=self.what)
        with _LOCK:
            _outstanding[self.key] = (
                _outstanding.get(self.key, 0) + self.needed)
        self._held = True
        return self.measured

    def __exit__(self, *exc):
        if self._held:
            with _LOCK:
                left = _outstanding.get(self.key, 0) - self.needed
                if left <= 0:
                    _outstanding.pop(self.key, None)
                else:
                    _outstanding[self.key] = left
            self._held = False
        return False


# What a single ledger write is assumed to need: one row, its revision, its
# request record and the journal page that carries them.
WRITE_BYTES = 8 * 1024

# What one import row costs: the raw fields, the parsed record, the source event
# and the classification decision.
IMPORT_ROW_BYTES = 16 * 1024

# What one uploaded source file costs beyond the bytes already in hand: the
# batch row, the per-row records and the journal.
IMPORT_FILE_OVERHEAD_BYTES = 64 * 1024


def reserve_write(path, needed_bytes: int = WRITE_BYTES, *, code: str = "WRITE_NO_SPACE",
                  what: str = "데이터를 쓰는 데") -> reservation:
    """The choke point every state-changing transaction calls."""
    return reservation(path, needed_bytes, code=code, what=what)


def reserve_conn(conn, needed_bytes: int, *, code: str, what: str) -> reservation:
    """The same choke point for a bare connection rather than a store.

    A connection can be told where its file is by `PRAGMA database_list`, which
    is the connection's own answer. Passing a path in from a caller would be a
    second source of truth about which volume a write lands on, and a probe on
    the wrong volume is a probe of the wrong disk.
    """
    row = conn.execute("PRAGMA database_list").fetchone()
    target = row[2] if row and row[2] else "."
    return reserve_write(target, needed_bytes, code=code, what=what)
