"""Profile synthetic or explicit read-only operational inputs; emit aggregates only."""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import sqlite3
import sys
import tempfile
import threading
import time
import tracemalloc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Meter:
    def __init__(self):
        self.sql_seconds = 0.0
        self.statements = 0
        self.io_seconds = 0.0
        self.io_bytes = 0


class Cursor(sqlite3.Cursor):
    def execute(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return super().execute(*args, **kwargs)
        finally:
            self.connection.meter.statements += 1
            self.connection.meter.sql_seconds += time.perf_counter() - started

    def fetchall(self):
        started = time.perf_counter()
        try:
            return super().fetchall()
        finally:
            self.connection.meter.sql_seconds += time.perf_counter() - started

    def fetchone(self):
        started = time.perf_counter()
        try:
            return super().fetchone()
        finally:
            self.connection.meter.sql_seconds += time.perf_counter() - started

    def __next__(self):
        started = time.perf_counter()
        try:
            return super().__next__()
        finally:
            self.connection.meter.sql_seconds += time.perf_counter() - started


class Connection(sqlite3.Connection):
    def execute(self, *args, **kwargs):
        return self.cursor(factory=Cursor).execute(*args, **kwargs)


def profiled(call, conn):
    meter = conn.meter = Meter()
    read_bytes, read_text = Path.read_bytes, Path.read_text

    def reading(original):
        def invoke(path, *args, **kwargs):
            start = time.perf_counter()
            result = original(path, *args, **kwargs)
            meter.io_seconds += time.perf_counter() - start
            meter.io_bytes += len(result)
            return result
        return invoke

    before = conn.total_changes
    profile = cProfile.Profile()
    with patch.object(Path, 'read_bytes', reading(read_bytes)), patch.object(Path, 'read_text', reading(read_text)):
        start = time.perf_counter()
        profile.enable()
        result = call()
        profile.disable()
        elapsed = time.perf_counter() - start
    assert conn.total_changes == before
    stats = pstats.Stats(profile)
    functions = []
    render_self = 0.0
    for (file, line, name), (cc, nc, tt, ct, callers) in stats.stats.items():
        if file.startswith(str(ROOT)):
            file = str(Path(file).relative_to(ROOT)).replace('\\', '/')
        else:
            file = Path(file).name
        if file in ('webapp/card_cleanup_ui.py', 'webapp/card_evidence_ui.py'):
            render_self += tt
        functions.append(dict(file=file, function=name, calls=nc, self_ms=tt*1000, cumulative_ms=ct*1000))
    return result, dict(total_ms=elapsed*1000, sql_ms=meter.sql_seconds*1000,
        sql_statements=meter.statements, file_io_ms=meter.io_seconds*1000, file_io_bytes=meter.io_bytes,
        render_self_ms=render_self*1000, python_other_ms=max(0, elapsed-meter.sql_seconds-meter.io_seconds-render_self)*1000,
        read_only=True, top_functions=sorted(functions,key=lambda r:r['cumulative_ms'],reverse=True)[:22])


def setup_synthetic(root, rows, trip_count):
    from webapp.ledger_store import LedgerStore
    from webapp import ledger_board
    from webapp.tests.test_expense_cleanup import card_rows, unassigned_row
    store = LedgerStore(root/'synthetic.sqlite', seed_demo=False)
    ledger_board.bind_store(store)
    card_rows(store, rows)
    store.conn.execute("UPDATE transactions SET classification_source='inference'")
    unassigned_row(store)
    store.conn.commit()
    path = store.path
    store.conn.close()
    store.conn = sqlite3.connect(path, factory=Connection, check_same_thread=False)
    store.conn.meter = Meter()
    trips = [dict(trip_id='trip-'+str(i), starts_on='2026-10-01', ends_on='2026-10-05') for i in range(trip_count)]
    return store, trips


def setup_operational(path):
    from webapp.ledger_store import LedgerStore
    from webapp import ledger_board
    # Bypass constructors that initialize schema/leases. This is a diagnostic
    # read facade, never an application writer or authenticated HTTP handler.
    store = object.__new__(LedgerStore)
    store.path = path
    store.conn = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, factory=Connection)
    store.conn.meter = Meter()
    store.conn.execute('PRAGMA query_only=ON')
    store.conn.execute('BEGIN')
    store._lock = threading.RLock()
    store._space_hold = None
    ledger_board.bind_store(store)
    trips = [dict(t, trip_id=t['tab_id']) for t in store.list_trips()]
    return store, trips


def run(args):
    os.environ['WEBLEDGER_CARD_SCHEMA_POLICY'] = 'require' if args.operational_db else 'create'
    os.environ['WEBLEDGER_UNIFIED_DB'] = '1'
    from webapp import card_flow, ledger_board
    from app import automatic_classification as policy
    with tempfile.TemporaryDirectory(prefix='cost-performance-') as directory:
        store, trips = setup_operational(args.operational_db) if args.operational_db else setup_synthetic(Path(directory), args.rows, args.trips)
        results = []
        calls = {'plan':lambda:policy.plan(store.conn,trips), 'cleanup':lambda:card_flow.render_expense_cleanup(store,'diagnostic-no-auth-token')}
        # Explicit synthetic OTA projection excludes network/source discovery.
        # Operational cleanup authority/OTA configuration is supplied by the
        # separate host-side diagnostic; plan always uses read-only DB input.
        try:
            for name in args.phases.split(','):
                if args.operational_db and name == 'cleanup':
                    raise ValueError('operational full render requires host-side configuration harness')
                with patch.object(card_flow,'_ota_entries_by_card',lambda *a,**kw:{}):
                    output,measurement = profiled(calls[name],store.conn)
                encoded = json.dumps(output,sort_keys=True,ensure_ascii=False,default=str).encode()
                measurement.update(phase=name,output_sha256=hashlib.sha256(encoded).hexdigest(),output_bytes=len(encoded))
                results.append(measurement)
            # A separate run avoids contaminating timing with tracemalloc.
            tracemalloc.start()
            with patch.object(card_flow,'_ota_entries_by_card',lambda *a,**kw:{}):
                calls[args.phases.split(',')[0]]()
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            result=dict(scope='operational-read-only' if args.operational_db else 'synthetic',rows=store.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],trips=len(trips),python=sys.version,measurements=results,allocation_peak_bytes_separate_run=peak,limits='cProfile instrumentation overhead; driver time includes fetch/iteration; render is presentation self time; filesystem bytes counted as characters for read_text; excludes HTTP/lock wait')
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=True))
        finally:
            ledger_board.bind_store(None);store.conn.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rows',type=int,default=2000)
    p.add_argument('--trips',type=int,default=70)
    p.add_argument('--operational-db',type=Path)
    p.add_argument('--phases',default='plan,cleanup')
    p.add_argument('--output',type=Path,required=True)
    run(p.parse_args())
