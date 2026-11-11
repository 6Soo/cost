"""Opt-in P2 read guard; ordinary P1 source readers keep their existing behavior."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
import zlib
import os

_GUARD = ContextVar('p2_source_read_guard', default=None)
BLOCK_BYTES = 1 << 20
MAX_JSON_FILE_BYTES = 64 << 20
MAX_RECORD_BYTES = 8 << 20


if os.name == 'nt':
    import ctypes
    class _Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.GetCurrentProcess.restype = ctypes.c_void_p
    _kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters)]


def process_read_bytes():
    """Windows logical ReadTransferCount, also counting SQLite's native I/O.

    Includes concurrent reads in this process: conservative for a P2 budget.
    Other platforms retain exact guarded file bytes plus source-size preflight.
    """
    if os.name == 'nt':
        counters = _Counters()
        if not _kernel.GetProcessIoCounters(_kernel.GetCurrentProcess(), ctypes.byref(counters)):
            raise OSError(ctypes.get_last_error(), 'GetProcessIoCounters')
        return counters.read_bytes
    return 0


@contextmanager
def guarded(check, consume):
    failed = []
    def checked():
        try:
            check()
        except Exception as exc:
            failed.append(exc)
            raise
    token = _GUARD.set((checked, consume))
    try:
        yield
    except sqlite3.OperationalError:
        if failed:
            raise failed[-1] from None
        raise
    finally:
        _GUARD.reset(token)


def checkpoint():
    guard = _GUARD.get()
    if guard:
        guard[0]()


def read_text(path):
    guard = _GUARD.get()
    if not guard:
        return Path(path).read_text(encoding='utf-8')
    chunks, size = [], 0
    with Path(path).open('rb') as handle:
        while True:
            checkpoint()
            # Reserve before read, including a file growing after its stat.
            available = min(BLOCK_BYTES, MAX_JSON_FILE_BYTES - size + 1)
            guard[1](available, reserve=True)
            block = handle.read(available)
            guard[1](len(block))
            checkpoint()
            if not block:
                break
            size += len(block)
            if size > MAX_JSON_FILE_BYTES:
                raise ValueError('P2_SOURCE_RECORD_TOO_LARGE')
            chunks.append(block)
    return b''.join(chunks).decode('utf-8')


def record(value):
    checkpoint()
    if _GUARD.get() and len(value) > MAX_RECORD_BYTES:
        raise ValueError('P2_SOURCE_RECORD_TOO_LARGE')
    return value


def message(payload):
    if _GUARD.get():
        record(json.dumps(payload, ensure_ascii=False))


def unpack(value):
    record(value)
    if isinstance(value, bytes):
        if _GUARD.get():
            decoder = zlib.decompressobj()
            raw = decoder.decompress(value, MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES or not decoder.eof:
                raise ValueError('P2_SOURCE_RECORD_TOO_LARGE')
        else:
            raw = zlib.decompress(value)
        value = raw.decode('utf-8')
    result = json.loads(record(value))
    checkpoint()
    return result


def guard_connection(conn):
    """Check SQLite work during scans/sorts and before materializing each row."""
    if not _GUARD.get():
        return conn
    def progress():
        # sqlite replaces callback exceptions by OperationalError; preserve the
        # original cancellation for callers through the following row checks.
        checkpoint()
        return 0
    def row_factory(cursor, values):
        checkpoint()
        for value in values:
            if isinstance(value, (str, bytes)):
                record(value)
        return sqlite3.Row(cursor, values)
    conn.set_progress_handler(progress, 1000)
    conn.row_factory = row_factory
    return conn
