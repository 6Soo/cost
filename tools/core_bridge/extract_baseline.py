"""Produce the design §3.4 extractor baseline: run the Python OTA extractor on the preserved originals.

The events are customer text (merchants, bookings), so they are written only under the protected
``<host-root>/data/backups/`` folder, never inside the repository. The live evidence store is opened
``mode=ro`` and copied with the SQLite backup API for a consistent snapshot; the live file is never
written. A pre-made copy may be passed instead of the live file. Git records the production command,
the Python SHA and the count (plus the baseline hash) — never the customer text.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .ota_input import DEFAULT_HOST, ROOT, _inside, _key, _sources, is_live


def _backup(live, workdir):
    """A consistent snapshot of the live store, read from a read-only connection into a fresh copy."""
    dst = Path(workdir) / 'ota-evidence.sqlite'
    with closing(sqlite3.connect(Path(live).resolve().as_uri() + '?mode=ro', uri=True)) as src:
        src.execute('PRAGMA query_only=ON')
        with closing(sqlite3.connect(str(dst))) as dst_conn:
            src.backup(dst_conn)
    return dst


def write_baseline(out, events):
    from .commands import canonical
    text = json.dumps(canonical({'events': events}), ensure_ascii=False, sort_keys=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    return {'events': len(events), 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def capture(request, error):
    """Write the extractor baseline for the preserved originals named in ``request``; return counts only."""
    for key in ('ota_evidence', 'out'):
        if not request.get(key):
            raise error(f'{key.upper()}_REQUIRED')
    host = request.get('host_root') or DEFAULT_HOST
    out = Path(request['out'])
    data = Path(host) / 'data'
    if _inside(out, ROOT):
        raise error('OUT_INSIDE_REPO')
    if not _inside(out, data / 'backups') or _key(out) == _key(data / 'backups'):
        raise error('OUT_NOT_PROTECTED')
    if out.exists():
        raise error('OUT_EXISTS')
    evidence = Path(request['ota_evidence'])
    if not evidence.is_file():
        raise error('DB_NOT_FOUND', 'ota_evidence')
    backups = data / 'backups'
    backups.mkdir(parents=True, exist_ok=True)
    live = data / 'ota-evidence.sqlite'
    with tempfile.TemporaryDirectory(prefix='extract-baseline-', dir=str(backups)) as work:
        if is_live(evidence, live):
            evidence = _backup(evidence, work)
        sources = _sources(evidence, work)
        from app import ota_payments
        events = ota_payments.build_ota_payment_events(sources)
        return write_baseline(out, events)
