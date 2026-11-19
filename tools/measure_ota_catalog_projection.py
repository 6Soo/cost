"""Read-only audit of the stored OTA catalog projection against raw reconstruction.

In one ``app.ota_store.connect_read`` snapshot, compares the stored
``ota_catalog_rows`` projection of the current portal revisions with the
``_catalog_read_rows`` arrays rebuilt from the preserved raw entries
(``_entries`` verifies the raw hashes). Equality is exact on the canonical
encoded arrays, including row order and value types. Each timing is the
median of ``repeats`` runs (1..20) of that side's read function.

Read-only: the store is opened ``mode=ro``; no database is written or
created. Output carries only counts, timings, and fixed error codes —
never raw text, row IDs, paths, or exception bodies.

Usage: python -I tools/measure_ota_catalog_projection.py --db PATH [--repeats N]
Exit codes: 0 match, 2 mismatch, 3 failure (fixed JSON code). An empty
projection on both sides is NO_DATA, never a passing match.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
import zlib
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ota_store  # noqa: E402  (needs the path bootstrap above)

INPUT_INVALID = 'OTA_CATALOG_MEASURE_INPUT_INVALID'
STORE_INVALID = 'OTA_CATALOG_MEASURE_STORE_INVALID'
RECONSTRUCT_FAILED = 'OTA_CATALOG_MEASURE_RECONSTRUCT_FAILED'
NO_DATA = 'OTA_CATALOG_MEASURE_NO_DATA'
ERROR_CODES = (INPUT_INVALID, STORE_INVALID, RECONSTRUCT_FAILED, NO_DATA)
EXIT_MATCH = 0
EXIT_MISMATCH = 2
EXIT_FAILURE = 3
MIN_REPEATS = 1
MAX_REPEATS = 20


def _stored_projection(conn):
    return [ota_store.unpacked(row['payload_json'])
            for row in ota_store._current_rows(conn, 'ota_catalog_rows', 'portal_database')]


def _reconstructed_projection(conn):
    rows = []
    for source in conn.execute("SELECT current_revision FROM ota_sources "
                               "WHERE kind='portal_database' ORDER BY ordinal"):
        catalog = ota_store._entries(conn, source['current_revision'])['_catalog_read_rows']
        if not isinstance(catalog, list) or not all(isinstance(row, dict) for row in catalog):
            raise ValueError(RECONSTRUCT_FAILED)
        rows.extend(catalog)
    return rows


def _median_ms(read, repeats):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = read()
        samples.append((time.perf_counter() - start) * 1000.0)
    return round(statistics.median(samples), 3), result


def measure(path, *, repeats=5):
    """Compare stored vs reconstructed catalog projection in one read snapshot.

    Raises ValueError with a fixed error code on input or store failure;
    exception bodies are never part of the code or the CLI output.
    """
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not MIN_REPEATS <= repeats <= MAX_REPEATS:
        raise ValueError(INPUT_INVALID)
    try:
        valid_path = isinstance(path, (str, os.PathLike)) and Path(path).is_file()
    except (OSError, ValueError):
        valid_path = False
    if not valid_path:
        raise ValueError(INPUT_INVALID)
    try:
        conn = ota_store.connect_read(path)
    except (OSError, sqlite3.Error):
        raise ValueError(STORE_INVALID) from None
    with closing(conn):
        try:
            schema = conn.execute(
                "SELECT value FROM ota_store_meta WHERE key='schema_version'").fetchone()
            if not schema or schema[0] != ota_store.SCHEMA:
                raise ValueError(STORE_INVALID)
            stored_ms, stored = _median_ms(lambda: _stored_projection(conn), repeats)
        except (sqlite3.Error, ValueError, zlib.error):
            raise ValueError(STORE_INVALID) from None
        try:
            rebuilt_ms, rebuilt = _median_ms(lambda: _reconstructed_projection(conn), repeats)
        except (sqlite3.Error, ValueError, KeyError, zlib.error):
            raise ValueError(RECONSTRUCT_FAILED) from None
    if not stored and not rebuilt:
        raise ValueError(NO_DATA)
    return {'match': ota_store.encoded(stored) == ota_store.encoded(rebuilt),
            'stored_rows': len(stored), 'reconstructed_rows': len(rebuilt),
            'stored_ms': stored_ms, 'reconstructed_ms': rebuilt_ms}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({'error': INPUT_INVALID}, sort_keys=True))
        self.exit(EXIT_FAILURE)


def main(argv=None):
    parser = _Parser(description='Audit stored vs reconstructed OTA catalog projection (read-only).')
    parser.add_argument('--db', required=True, help='integrated OTA store path (opened read-only)')
    parser.add_argument('--repeats', type=int, default=5,
                        help='timing runs per side, 1..20 (default: 5)')
    args = parser.parse_args(argv)
    try:
        report = measure(args.db, repeats=args.repeats)
    except ValueError as error:
        code = str(error)
        print(json.dumps({'error': code if code in ERROR_CODES else STORE_INVALID}, sort_keys=True))
        return EXIT_FAILURE
    except Exception:
        print(json.dumps({'error': STORE_INVALID}, sort_keys=True))
        return EXIT_FAILURE
    print(json.dumps(report, sort_keys=True))
    return EXIT_MATCH if report['match'] else EXIT_MISMATCH


if __name__ == '__main__':
    sys.exit(main())
