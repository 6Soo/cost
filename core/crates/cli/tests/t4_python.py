"""T4 helper: build a synthetic board DB and run the Python `apply` on it (설계 §3.3, U11 수락 조건).

    python -I t4_python.py build <scenario> <db> <opts.json>
    python -I t4_python.py apply <db> <opts.json> <fixed-now>
    python -I t4_python.py plan <db> <opts.json>

Synthetic data only. `apply` freezes `utc_now` so Python and Rust change_log/history timestamps can be compared.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app import automatic_classification as policy  # noqa: E402
from app import db as app_db  # noqa: E402
from webapp import ledger_store_schema as board_schema  # noqa: E402

HASH = 'a' * 64


def txn(c, tid, *, approval='2026-10-03', merchant='SYNTHETIC SHOP', state='needs_review', source='', item='',
        trip='', tab='', direction='purchase', decided=None, raw='card-category:', amount=-12000):
    c.execute(
        "INSERT INTO transactions(transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,transaction_direction,"
        "transaction_kind,approval_number,original_approval_number,approval_date,posting_date,merchant,"
        "merchant_normalized,amount_krw,description_raw,row_index,raw_row_json,classification_state,"
        "classification_source,item,display_tab_id,trip_id,decided_at,created_at) "
        "VALUES (?,?,'b1','K','1111','credit',?,'일시불',?,'',?,?,?,?,?,?,0,'{}',?,?,?,?,?,?,'2026-10-04')",
        (tid, HASH, direction, 'AP-' + tid, approval, approval, merchant, merchant, amount, raw, state, source,
         item, tab, trip, decided))


def ledger(c, tid, item='', tab='unclassified', trip=''):
    c.execute("INSERT INTO ledger_entries VALUES (?,'b1',?,'',?,?,-12000,'SYNTHETIC SHOP','2026-10-03','purchase',?,'2026-10-05')",
              (tid, item, tab, trip, HASH))


def board(c, tid, tab='unclassified', **payload):
    body = dict(item='', display_tab_id=tab, revision=1, confirmed_by='automatic')
    body.update(payload)
    c.execute("INSERT INTO board_rows VALUES (?,'expense',?,1,?)", ('card-' + tid, tab, json.dumps(body)))


def create(kind, path, opts_path):
    c = sqlite3.connect(path)
    c.executescript(app_db.SCHEMA_SQL)
    c.executescript(board_schema.SCHEMA_SQL)
    cols = [r[1] for r in c.execute('PRAGMA table_info(trip_tabs)')]
    for tab, key, dest, start, end in (('A', '1001', 'Tokyo', '2026-10-01', '2026-10-05'),
                                       ('B', '1002', 'Osaka', '2026-10-10', '2026-10-13')) if kind != 'unattributable' else ():
        values = {'tab_id': tab, 'display_key': key, 'destination': dest, 'starts_on': start, 'ends_on': end}
        for col in cols:
            if col not in values and col in ('created_at', 'updated_at'):
                values[col] = '2026-09-01'
        c.execute('INSERT INTO trip_tabs(%s) VALUES (%s)' % (','.join(values), ','.join('?' * len(values))),
                  tuple(values.values()))
    opts = {}
    if kind == 'general':
        txn(c, 'g1', merchant='음식점 SYNTHETIC'); ledger(c, 'g1'); board(c, 'g1')
        txn(c, 'g2', approval='2026-10-12', merchant='SYNTHETIC HOTEL', raw='card-category:호텔')
        txn(c, 'g3', state='classified', source='inference', item='식비'); board(c, 'g3')
        txn(c, 'g4', approval='2025-05-02', merchant='음식점 SYNTHETIC'); ledger(c, 'g4'); board(c, 'g4')
        txn(c, 'g5', state='classified', source='user_decision', item='식비', trip='A', tab='A', decided='2026-10-06')
        txn(c, 'g6'); c.execute("INSERT INTO transaction_review_holds VALUES ('g6',?,'user_hold','x')", (HASH,))
        txn(c, 'g7', state='classified', source='ai_inference', item='식비')
        txn(c, 'g9', approval='2026-10-04', merchant='SYNTHETIC AIRWAYS', raw='card-category:항공'); ledger(c, 'g9', item='항공료')
    elif kind == 'unattributable':
        txn(c, 'u1', approval='2026-10-03', merchant='음식점 SYNTHETIC')
        txn(c, 'u2', approval='2026-12-20', merchant='SYNTHETIC UNKNOWN')
    elif kind == 'booking':
        txn(c, 'b1', state='classified', source='inference', item='숙박비', trip='A', tab='A')
        ledger(c, 'b1', item='숙박비', tab='A', trip='A'); board(c, 'b1', tab='A', item='숙박비')
        trips = [dict(trip_id='A', starts_on='2026-10-01', ends_on='2026-10-05'),
                 dict(trip_id='B', starts_on='2026-10-10', ends_on='2026-10-13')]
        evidence = {'b1': dict(source_hash=HASH, trip_id='B', item='숙박비', basis='예약 이용기간 2026-10-13~2026-10-14')}
        opts = dict(trips=trips, evidence=evidence, reconsider=True, transaction_ids=['b1'])
    c.commit()
    c.close()
    Path(opts_path).write_text(json.dumps(opts), encoding='utf-8')


def default_trips(c):
    cursor = c.execute('SELECT tab_id,display_key,destination,starts_on,ends_on FROM trip_tabs WHERE deleted=0')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r), trip_id=r[0]) for r in cursor]


def run_apply(path, opts_path, now, dry=False):
    app_db.utc_now = lambda: now
    opts = json.loads(Path(opts_path).read_text(encoding='utf-8'))
    c = sqlite3.connect(path, isolation_level=None)
    trips = opts.get('trips') or default_trips(c)
    ids = opts.get('transaction_ids')
    kwargs = dict(nets=opts.get('nets'), transaction_ids=set(ids) if ids is not None else None,
                  reconsider=bool(opts.get('reconsider')), evidence=opts.get('evidence'))
    preview = policy.plan(c, trips, **kwargs)
    summary = None if dry else policy.apply(c, preview, trips, **kwargs)
    c.close()
    print(json.dumps({'digest': preview['digest'], 'summary': summary, 'targets': len(preview['targets']),
                      'correction': any(t.get('booking_trip_correction') for t in preview['targets'])}))


if __name__ == '__main__':
    mode, *rest = sys.argv[1:]
    if mode == 'build':
        create(*rest)
    elif mode == 'plan':
        run_apply(rest[0], rest[1], '', dry=True)
    else:
        run_apply(*rest)
