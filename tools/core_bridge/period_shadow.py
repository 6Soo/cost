"""Shadow comparison of the Rust period rule against Python ``verified_period_for`` on copies of the live data.

Reads the live host databases only through the sqlite backup API (copies go under the protected
``data/backups/`` folder), runs one OTA reconciliation on the copies, then compares per card row:
Python's verified period (expected) against ``costcore periods`` (Rust). Public output is counts only;
ids and periods are written to private files next to the copies.

    python -m tools.core_bridge.period_shadow --host-root D:/WebLedgerHost --out D:/WebLedgerHost/data/backups/<dir> --costcore <exe>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def backup(source: Path, target: Path) -> None:
    """A consistent copy through the sqlite backup API; the source is opened read-only."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as src, \
            closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def card_rows(board: Path) -> tuple[list[dict], set]:
    """Screen rows of card transactions: stored period and reservation number from the board payload."""
    rows = []
    with closing(sqlite3.connect(board.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        payloads = dict(conn.execute("SELECT row_id, payload_json FROM board_rows WHERE row_id LIKE 'card-%'"))
        for (tid,) in conn.execute('SELECT transaction_id FROM transactions ORDER BY transaction_id'):
            row_id, payload = 'card-' + tid, payloads.get('card-' + tid)
            try:
                body = json.loads(payload) if payload else {}
            except ValueError:
                body = {}
            rows.append({'row_id': row_id, 'service_period': str(body.get('service_period') or ''),
                         'reservation_no': str(body.get('reservation_no') or '')})
        manual = {r[0] for r in conn.execute("SELECT row_id FROM board_manual_overrides WHERE field='service_period'")}
    return rows, manual


def snapshot(data_dir: Path, mail_dir: Path, review_db: Path) -> dict:
    os.environ['WEBLEDGER_OTA_REVIEW_DB'] = str(review_db)
    os.environ['WEBLEDGER_OTA_MAIL_DIR'] = str(mail_dir)
    from webapp import ota_payment_review
    from webapp.ledger_store import LedgerStore
    store = LedgerStore(data_dir / 'board.sqlite', seed_demo=False)
    try:
        return ota_payment_review.reconcile(store)['data']
    finally:
        store.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--host-root', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--costcore', required=True)
    ap.add_argument('--reuse', action='store_true', help='keep the copies already in --out')
    args = ap.parse_args(argv)
    host, out = Path(args.host_root), Path(args.out)
    live = host / 'data'
    work = out / 'period'
    data_dir = work / 'data'
    review_db = work / 'review' / 'ota-review.sqlite'
    if not (args.reuse and review_db.is_file()):
        backup(live / 'board.sqlite', data_dir / 'board.sqlite')
        backup(live / 'ota-evidence.sqlite', data_dir / 'ota-evidence.sqlite')
        backup(live / 'ota-review' / 'ota-review.sqlite', review_db)
    (data_dir / 'ota-sources.json').write_text(json.dumps({
        'schema_version': 'ota-sources-v1', 'unified_database': str(data_dir / 'ota-evidence.sqlite')}), encoding='utf-8')
    mail_dir = live / 'ota-mail'

    rows, manual = card_rows(data_dir / 'board.sqlite')
    data = snapshot(data_dir, mail_dir, review_db)
    from tools.core_bridge.periods import facts_from_snapshot
    from webapp.ledger_stay_evidence import index_from_snapshot, verified_period_for
    index = index_from_snapshot(data, manual)
    expected = {r['row_id'][5:]: verified_period_for(r, index) for r in rows}
    facts = facts_from_snapshot(data, manual)
    facts_file = work / 'facts.json'
    facts_file.write_text(json.dumps({'facts': facts}, ensure_ascii=False), encoding='utf-8')

    rust_file = work / 'rust.jsonl'
    run = subprocess.run([args.costcore, 'periods', '--db', str(data_dir / 'board.sqlite'), '--host-root', str(host),
                          '--periods', str(facts_file), '--private-out', str(rust_file)],
                         capture_output=True, text=True, encoding='utf-8')
    public = json.loads(run.stdout.splitlines()[0])
    if not public.get('ok'):
        print(json.dumps({'status': 'ERROR', 'costcore': public}))
        return 2
    got = {}
    for line in rust_file.read_text(encoding='utf-8').splitlines():
        item = json.loads(line)
        got[item['id']] = item['period']
    diffs = []
    kinds = Counter()
    for tid in sorted(set(expected) | set(got)):
        a, b = expected.get(tid), got.get(tid)
        if a != b:
            kind = ('rust_missing' if b is None else 'python_missing' if a is None else
                    'python_blank_rust_period' if not a else 'python_period_rust_blank' if not b else 'periods_differ')
            kinds[kind] += 1
            diffs.append({'id': tid, 'python': a, 'rust': b, 'kind': kind})
    (work / 'diffs.jsonl').write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in diffs), encoding='utf-8')
    result = {'status': 'PASS' if not diffs else 'FAIL', 'rows': len(rows), 'python_with_period': sum(1 for v in expected.values() if v),
              'rust_with_period': sum(1 for v in got.values() if v), 'diffs': len(diffs), 'kinds': dict(kinds),
              'facts_transactions': len(facts), 'manual_overrides': len(manual)}
    print(json.dumps(result, sort_keys=True))
    return 0 if not diffs else 1


if __name__ == '__main__':
    raise SystemExit(main())
