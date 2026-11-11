"""Opt-in P2 read guard; ordinary P1 source readers keep their existing behavior."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
import zlib
import os
import itertools

_GUARD = ContextVar('p2_source_read_guard', default=None)
BLOCK_BYTES = 1 << 20
MAX_JSON_FILE_BYTES = 64 << 20
MAX_RECORD_BYTES = 8 << 20
P2_TEXT_BYTES = 96 << 10


def _bounded_text(value, limit=P2_TEXT_BYTES):
    """Keep a bounded, non-executable text view for P2 evidence only."""
    import re
    import html
    value = re.sub(r'(?is)<(script|style|svg|blockquote)\b[^>]*>.*?</\1\s*>', ' ', value)
    value = re.sub(r'(?is)<[^>]*>', '\n', value)
    value = html.unescape(value)
    value = re.sub(r'(?i)data:image/[^\s"\']+', '', value)
    value = re.sub(r'(?im)^\s*>.*$', '', value)
    value = re.split(r'(?im)^\s*(?:-+\s*original message\s*-+|On .+wrote:|보낸 사람:|--\s*$|sent from my\b)', value, maxsplit=1)[0]
    value = value.strip()
    raw = value.encode('utf-8')
    marker = '\n[생략: 원문 정리 또는 크기 상한에 따른 발췌]'
    if len(raw) <= limit:
        return value
    # Reserve space for the explicit marker; include windows around each type
    # of decision evidence before filling the remainder with the introduction.
    budget = limit - len(marker.encode('utf-8'))
    patterns = (r'예약\s*(?:번호|코드)|booking|reservation|confirmation',
                r'금액|결제|total|amount|[₩$€¥]|\b(?:KRW|USD|JPY|EUR)\b',
                r'\b20\d{2}[-/.년]\s*\d{1,2}|check.?in|check.?out',
                r'agoda|trip\.com|booking\.com|expedia|공급자')
    ranges = []
    for pattern in patterns:
        for match in itertools.islice(re.finditer(pattern, value, re.I), 12):
            ranges.append((max(0, match.start()-160), min(len(value), match.end()+320)))
    pieces = []
    covered = []
    for start, end in ranges:
        if any(a <= start and end <= b for a, b in covered):
            continue
        piece = value[start:end]
        size = len((piece + '\n').encode('utf-8'))
        if size <= budget:
            pieces.append(piece)
            covered.append((start, end))
            budget -= size
    prefix = raw[:max(0, budget)].decode('utf-8', errors='ignore')
    return ('\n'.join(pieces) + '\n' + prefix).strip() + marker


def bounded_payload(value):
    """Copy a mail payload while clipping only body text/data for P2."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in ('content', 'data', 'base64_url_content') and isinstance(item, str):
                out[key] = _bounded_text(item)
            else:
                out[key] = bounded_payload(item)
        return out
    if isinstance(value, list):
        return [bounded_payload(item) for item in value]
    return value


if os.name == 'nt':
    import ctypes
    class _Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.GetCurrentProcess.restype = ctypes.c_void_p
    _kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters)]
    class _BasicInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in ('created', 'accessed', 'written', 'changed')] + [
            ('attributes', ctypes.c_ulong)]
    _kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                   ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    _kernel.CreateFileW.restype = ctypes.c_void_p
    _kernel.GetFileInformationByHandleEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    _kernel.CloseHandle.argtypes = [ctypes.c_void_p]


def change_time(path, stat):
    """True metadata change time (Windows st_ctime is creation time).

    Detects same-size edits even when LastWriteTime is restored by copy tools.
    Opens attributes only, sharing read/write/delete; reads no source content.
    """
    if os.name != 'nt':
        return stat.st_ctime_ns
    handle = _kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'CreateFileW attributes')
    try:
        info = _BasicInfo()
        if not _kernel.GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), 'GetFileInformationByHandleEx')
        return info.changed
    finally:
        _kernel.CloseHandle(handle)


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


def active():
    return _GUARD.get() is not None


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
    if _GUARD.get() and len(value.encode('utf-8') if isinstance(value, str) else value) > MAX_RECORD_BYTES:
        raise ValueError('P2_SOURCE_RECORD_TOO_LARGE')
    return value


def message(payload):
    if not _GUARD.get():
        return payload
    # A provider payload may contain a large quoted/HTML body. Do not reject
    # the whole transaction; return a bounded copy for P2 assembly.
    return bounded_payload(payload)


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
