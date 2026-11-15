"""Capture the OTA solver input that ``CoreOtaPaymentBackend._data`` hands to ``match_ota_payment_events``.

The input file is what ``costcore shadow-links --ota-input`` reads. It holds customer text (merchants, bookings),
so it is written only under the protected ``<host-root>/data/backups/`` folder, never inside the repository.
Only copies are read: the board, OTA evidence and review databases are opened ``mode=ro``, and the live files
(``<host-root>/data/board.sqlite`` and friends) are refused with ``DB_IS_LIVE``.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST = 'D:/WebLedgerHost'


class _Captured(Exception):
    def __init__(self, events, transactions, kwargs):
        super().__init__('captured')
        self.events, self.transactions, self.kwargs = events, transactions, kwargs


class _SpyPayments:
    """The real ``app.ota_payments`` except that the solver call is recorded and stops ``_data`` there."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def match_ota_payment_events(self, events, transactions, **kwargs):
        raise _Captured(events, transactions, kwargs)


class _ReadOnlyBoard:
    """What ``_data`` reads from a board: a read-only connection and its path."""

    def __init__(self, conn, path):
        self.conn, self.path = conn, str(path)


def _key(path):
    return os.path.normcase(os.path.realpath(str(path)))


def is_live(path, live):
    """True when ``path`` is the live file: same resolved path (also ``\\\\?\\`` forms) or the same file (hard link)."""
    plain = lambda p: _key(str(p)[4:] if str(p).startswith('\\\\?\\') else p)  # noqa: E731
    if plain(path) == plain(live):
        return True
    try:
        return os.path.samefile(path, live)
    except OSError:  # one of them does not exist
        return False


def _inside(path, folder):
    path, folder = _key(path), _key(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def check_paths(error, *, host_root, databases, out):
    """Refuse live files and any output location outside the protected backups folder (error(code, detail))."""
    data = Path(host_root) / 'data'
    live = [data / 'board.sqlite', data / 'ota-evidence.sqlite', data / 'ota-review' / 'ota-review.sqlite']
    for path in databases:
        if any(is_live(path, target) for target in live):
            raise error('DB_IS_LIVE')
    if _inside(out, ROOT):
        raise error('OUT_INSIDE_REPO')
    if not _inside(out, data / 'backups') or _key(out) == _key(data / 'backups'):
        raise error('OUT_NOT_PROTECTED')
    if Path(out).exists():
        raise error('OUT_EXISTS')


def _sources(evidence, workdir):
    from app import ota_sources
    manifest = Path(workdir) / 'ota-sources.json'
    manifest.write_text(json.dumps({'schema_version': 'ota-sources-v1', 'unified_database': str(evidence)}),
                        encoding='utf-8')
    return ota_sources.resolve_sources(Path(evidence).parent, manifest_file=manifest)


def solver_input(board_path, review_path, sources, payments=None):
    """The solver input of one ``_data`` run, as the ``links`` bridge command (kind=ota) takes it."""
    from webapp.ota_payment_review import CoreOtaPaymentBackend
    review = importlib.import_module('app.ota_review')
    real = payments or importlib.import_module('app.ota_payments')
    target = Path(board_path).resolve()
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.row_factory = sqlite3.Row
        backend = CoreOtaPaymentBackend(_ReadOnlyBoard(conn, target), str(Path(review_path).resolve()), read_only=True,
                                        payments=_SpyPayments(real), store_type=review.OtaReviewStore,
                                        sources=sources)
        # The capture must reach the Python solver call even when the Rust producer switch is on in this environment.
        saved = os.environ.pop('WEBLEDGER_LINKS_PRODUCER', None)
        try:
            backend._data()
        except _Captured as captured:
            return {'kind': 'ota', 'events': captured.events, 'transactions': captured.transactions,
                    'existing_links': captured.kwargs.get('existing_links'),
                    'rules': captured.kwargs.get('rules'),
                    'frozen_groups': captured.kwargs.get('frozen_groups')}
        finally:
            if saved is not None:
                os.environ['WEBLEDGER_LINKS_PRODUCER'] = saved
            backend.close()
    raise RuntimeError('SOLVER_NOT_REACHED')


def capture(request, error):
    """Write the solver input for the copies named in ``request``; return counts only."""
    for key in ('db', 'ota_evidence', 'review_db', 'out'):
        if not request.get(key):
            raise error(f'{key.upper()}_REQUIRED')
    host = request.get('host_root') or DEFAULT_HOST
    out = Path(request['out'])
    check_paths(error, host_root=host, databases=[request['db'], request['ota_evidence'], request['review_db']],
                out=out)
    for key in ('db', 'ota_evidence', 'review_db'):
        if not Path(request[key]).is_file():
            raise error('DB_NOT_FOUND', key)
    with tempfile.TemporaryDirectory(prefix='ota-input-') as work:
        data = solver_input(request['db'], request['review_db'], _sources(request['ota_evidence'], work))
    return write_input(out, data)


def write_input(out, data):
    from tools.core_bridge.commands import canonical
    text = json.dumps(canonical(data), ensure_ascii=False, sort_keys=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    return {'events': len(data['events']), 'transactions': len(data['transactions']),
            'existing_links': len(data['existing_links'] or {}), 'rules': len(data['rules'] or ()),
            'frozen_groups': len(data['frozen_groups'] or ()),
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
