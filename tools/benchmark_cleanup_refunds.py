"""Compare read kernels with a committed baseline using synthetic rows only.

Run: python tools/benchmark_cleanup_refunds.py --baseline 61188520
Medians describe local kernels, not authenticated HTTP or network latency.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
import sqlite3
import subprocess
import sys
from threading import RLock
from time import perf_counter
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def baseline_module(revision, name, filename):
    source = subprocess.check_output(['git', 'show', revision + ':' + filename], cwd=ROOT).decode('utf-8-sig')
    module = ModuleType(name)
    module.__file__ = str(ROOT / filename)
    exec(compile(source, '<committed baseline>', 'exec'), module.__dict__)
    return module


def measure(call, repeats):
    expected = call()
    samples = []
    for _ in range(repeats):
        start = perf_counter()
        assert call() == expected, 'non-deterministic result'
        samples.append(perf_counter() - start)
    return expected, median(samples)


def run(revision, purchases=5000, repeats=5):
    from app import partial_refund
    from webapp import card_cleanup_queries, read_scope
    from webapp.card_flow import CardFlow
    old_refunds = baseline_module(revision, 'app._benchmark_refunds', 'app/partial_refund.py')
    old_cleanup = baseline_module(revision, 'webapp._benchmark_cleanup', 'webapp/card_cleanup_queries.py')
    db = sqlite3.connect(':memory:')
    try:
        db.execute('''CREATE TABLE transactions(transaction_id,transaction_direction,issuer,card_tail,
            merchant,merchant_normalized,amount_krw,approval_date,posting_date,approval_number,
            original_approval_number,duplicate_of,conflict_reason,parse_error,foreign_currency,
            foreign_amount,classification_state,item,display_tab_id,classification_basis,classification_source)''')
        db.execute('CREATE TABLE ledger_entries(transaction_id)')
        db.execute('CREATE TABLE board_rows(row_id)')
        rows, refund_ids = [], []
        for index in range(purchases):
            merchant = 'synthetic-' + str(index % 113)
            tail = str(index % 8)
            amount = 1000 + index
            for cancellation in range(2 if index % 10 == 0 else 1):
                tid = ('refund-' if cancellation else 'purchase-') + str(index)
                if cancellation:
                    refund_ids.append(tid)
                rows.append((tid, 'cancellation' if cancellation else 'purchase', 'synthetic', tail,
                    merchant, merchant, -amount if cancellation else amount, '2026-10-02', '2026-10-03',
                    '', '', None, '', '', '', '', 'classified', '현지경비', 'synthetic-trip', '', 'inference'))
        db.executemany('INSERT INTO transactions VALUES (' + ','.join('?' for _ in range(21)) + ')', rows)
        db.commit()
        before = db.total_changes
        board = SimpleNamespace(conn=db, _lock=RLock(), _card_pipeline=SimpleNamespace(store=SimpleNamespace(conn=db)))

        @read_scope.scoped
        def select(fn):
            return db.execute('SELECT t.transaction_id FROM transactions t WHERE ' + fn(board)).fetchall()

        with patch.object(CardFlow, 'trip_valid', lambda self, target: target == 'synthetic-trip'):
            old_rows, old_sql_time = measure(lambda: select(old_cleanup.completed_assignment_sql), repeats)
            new_rows, new_sql_time = measure(lambda: select(card_cleanup_queries.completed_assignment_sql), repeats)
        old_links, old_link_time = measure(lambda: old_refunds.refund_links(db, refund_ids), repeats)
        new_links, new_link_time = measure(lambda: partial_refund.refund_links(db, refund_ids), repeats)
        assert old_rows == new_rows and old_links == new_links
        assert db.total_changes == before
        return dict(baseline=revision, synthetic_purchases=purchases, cancellations=len(refund_ids),
            repeats=repeats, complete_output_equivalent=True, writes=0,
            cleanup=dict(before_seconds=old_sql_time, after_seconds=new_sql_time, speedup=old_sql_time/new_sql_time),
            refunds=dict(before_seconds=old_link_time, after_seconds=new_link_time, speedup=old_link_time/new_link_time))
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--purchases', type=int, choices=range(1, 20001), default=5000, metavar='1..20000')
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=5)
    args = parser.parse_args()
    print(json.dumps(run(args.baseline, args.purchases, args.repeats), indent=2))
