"""One-off correction of recorded lodging/flight trips whose trip does not overlap the verified booking period.

Owner approval 2026-11-15 (TRIP-033/036): move the rows whose current trip shares no day with the verified service
period; archived (closed) trips are allowed targets. Rows whose current trip overlaps but differs are only listed for
the AI reviewer. Real manual corrections and financial protections stay.

  preview: python tools/correct_booking_trips.py --host-root H --out PRIVATE_DIR
  apply:   ... --apply --request-id ID --expected-digest D --backup-evidence FILE
  revert:  ... --revert APPLIED_ID --request-id ID --backup-evidence FILE

Customer details (transaction ids, merchants, amounts) go only to PRIVATE_DIR; stdout carries counts and digests.
Google is never written; the paste lists are files for a person to paste.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUEST_SCOPE = 'booking_trip_correction_request'
ACTOR = 'booking-trip-correction'
LIVE_HOST = Path('D:/WebLedgerHost')


class Refused(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def configure(host: Path):
    """The same environment the launcher gives the Board, read from this host's config."""
    from tools.launch_web_ledger import apply_ota_review, apply_product_features
    options = json.loads((host / 'config/card-flow.json').read_text(encoding='utf-8-sig'))
    options = dict(options, insurance_review={'enabled': False})
    apply_ota_review(options)
    apply_product_features(options, host / 'data')
    review = host / 'config/real-review.json'
    if review.is_file():
        os.environ['WEBLEDGER_REVIEW_CONFIG'] = str(review)
    os.environ['WEBLEDGER_CARD_SCHEMA_POLICY'] = 'require'


def snapshot(host: Path, cache: Path | None):
    """One OTA reconciliation of this host (minutes); reused from `cache` while the OTA inputs are unchanged."""
    from app import automatic_classification as policy
    from webapp import ota_payment_review
    from webapp.ledger_store import LedgerStore
    store = LedgerStore(host / 'data/board.sqlite', seed_demo=False)
    try:
        key = ota_payment_review.current_input_key(store, (*policy.FIELDS, 'revision'))
        if cache is not None and cache.is_file():
            saved = pickle.loads(cache.read_bytes())
            if saved.get('key') == key:
                return saved['current'], key
        result = ota_payment_review.reconcile_in_child(store)
    finally:
        store.close()
    current = {'data': result['data'], 'generation': 'tool-' + key[:16]}
    if cache is not None:
        cache.write_bytes(pickle.dumps({'key': key, 'current': current}, protocol=pickle.HIGHEST_PROTOCOL))
    return current, key


def flow_for(conn, host, current):
    from tools.complete_card_classification import read_flow
    flow = read_flow(conn, host)
    flow._held_ota_snapshot = lambda: (current, True)
    return flow


def categorize(records):
    """Split rows whose chosen trip differs from the current one; the apply scope is `non_overlap` only."""
    groups = defaultdict(list)
    for record in records:
        if record['chosen_trip'] == record['current_tab']:
            groups['matching'].append(record)
        elif record['protection'] == 'MANUAL':
            groups['manual'].append(record)
        elif record['protection']:
            groups['protected'].append(record)
        elif not record['chosen_trip']:
            groups['no_target'].append(record)
        elif record['current_overlaps']:
            groups['overlap_differs'].append(record)
        else:
            groups['non_overlap'].append(record)
    return groups


def plan_digest(targets):
    return _sha(sorted((r['transaction_id'], r['digest'], r['current_tab'], r['chosen_trip']) for r in targets))


def _paste_rows(conn, records):
    rows = []
    for record in records:
        tx = conn.execute('SELECT approval_date, posting_date, merchant, item, amount_krw FROM transactions'
                          ' WHERE transaction_id=?', (record['transaction_id'],)).fetchone()
        rows.append({'transaction_id': record['transaction_id'], 'date': tx[0] or tx[1] or '', 'payee': tx[2] or '',
                     'category': tx[3] or '', 'period': f"{record['period']['starts_on']}~{record['period']['ends_on']}",
                     'reservation_no': '', 'evidence': 'card', 'amount_krw': tx[4], 'status': 'ready'})
    return rows


def write_paste_lists(conn, trips, records, out: Path):
    """Per trip: rows to add to the target trip tab and rows to remove from the source tab (TSV, 7 columns B:H)."""
    from app.google_tsv import expense_tsv
    index = []
    for side, key in (('add', 'chosen_trip'), ('remove', 'current_tab')):
        grouped = defaultdict(list)
        for record in records:
            grouped[record[key]].append(record)
        for tab, members in sorted(grouped.items()):
            trip = trips.get(tab) or {}
            name = trip.get('display_key') or tab or 'unassigned'
            result = expense_tsv(_paste_rows(conn, members), layout='rev')
            path = out / f'paste-{side}-{name}.tsv'
            path.write_text(result['tsv'], encoding='utf-8')
            index.append({'side': side, 'tab_id': tab, 'display_key': name, 'archived': bool(trip.get('archived')),
                          'rows': result['row_count'], 'total_krw': result['total_krw'], 'held': result['held'],
                          'file': path.name})
    (out / 'paste-index.json').write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    return index


def _brief(record, trips):
    return {**{k: record[k] for k in ('transaction_id', 'item', 'period', 'current_tab', 'chosen_trip',
                                      'current_overlaps', 'chosen_archived', 'protection', 'digest')},
            'current_name': (trips.get(record['current_tab']) or {}).get('display_key', ''),
            'chosen_name': (trips.get(record['chosen_trip']) or {}).get('display_key', '')}


def preview(conn, host, current, out: Path):
    from webapp.booking_period_rejudge import assess
    flow = flow_for(conn, host, current)
    records = assess(flow, current, include_archived=True)
    groups = categorize(records)
    trips = {t['tab_id']: t for t in flow.board.list_trips(include_archived=True)}
    targets = groups['non_overlap']
    counts = {'assessed': len(records), 'mismatched': len(records) - len(groups['matching']),
              **{name: len(groups[name]) for name in ('manual', 'protected', 'no_target', 'overlap_differs',
                                                     'non_overlap')},
              'to_archived': sum(r['chosen_archived'] for r in targets),
              'protection_reasons': dict(Counter(r['protection'] for r in groups['protected']))}
    report = {'digest': plan_digest(targets), 'counts': counts,
              'targets': [_brief(r, trips) for r in targets],
              'review_list': [_brief(r, trips) for r in groups['overlap_differs']],
              'manual': [_brief(r, trips) for r in groups['manual']],
              'no_target': [_brief(r, trips) for r in groups['no_target']]}
    out.mkdir(parents=True, exist_ok=True)
    (out / 'preview.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'review-list.json').write_text(json.dumps(report['review_list'], ensure_ascii=False, indent=1),
                                          encoding='utf-8')
    planned = out / 'planned-paste'
    planned.mkdir(exist_ok=True)
    write_paste_lists(conn, trips, targets, planned)
    return report, targets, trips


def _stored_request(conn, request_id):
    row = conn.execute('SELECT response_json FROM requests WHERE request_id=? AND scope=?',
                       ('booking-trip-correction:' + request_id, REQUEST_SCOPE)).fetchone()
    return json.loads(row[0]) if row else None


def _store_request(conn, request_id, payload, response):
    from app.db import utc_now
    conn.execute('INSERT INTO requests VALUES (?,?,?,?,?)',
                 ('booking-trip-correction:' + request_id, REQUEST_SCOPE, _sha(payload),
                  json.dumps(response, ensure_ascii=False, sort_keys=True), utc_now()))


def apply(conn, host, current, out: Path, *, request_id, expected_digest):
    from webapp.booking_period_rejudge import correct
    saved = _stored_request(conn, request_id)
    if saved is not None:
        if saved.get('kind') != 'apply' or saved.get('digest') != expected_digest:
            raise Refused('REQUEST_ID_REUSED')
        return dict(saved, written=0, replayed=True)
    report, targets, trips = preview(conn, host, current, out)
    if report['digest'] != expected_digest:
        raise Refused('PREVIEW_STALE')
    conn.execute('BEGIN IMMEDIATE')
    try:
        for record in targets:
            correct(conn, record, request_id=request_id, actor=ACTOR)
        response = {'kind': 'apply', 'digest': expected_digest, 'written': len(targets),
                    'transaction_ids': [r['transaction_id'] for r in targets]}
        _store_request(conn, request_id, {'kind': 'apply', 'digest': expected_digest}, response)
        conn.execute('COMMIT')
    except BaseException:
        conn.rollback()
        raise
    applied = out / 'applied-paste'
    applied.mkdir(exist_ok=True)
    write_paste_lists(conn, trips, targets, applied)
    return dict(response, transaction_ids=None)


def revert(conn, out: Path, *, applied_id, request_id):
    """Restore the before values of one applied request, only where the row still holds the applied values."""
    import app.automatic_classification as policy
    from app.db import utc_now
    saved = _stored_request(conn, request_id)
    if saved is not None:
        if saved.get('kind') != 'revert' or saved.get('reverts') != applied_id:
            raise Refused('REQUEST_ID_REUSED')
        return dict(saved, written=0, replayed=True)
    events = [(subject, json.loads(detail)) for subject, detail in conn.execute(
        'SELECT subject, detail_json FROM change_log WHERE kind=? ORDER BY entry_id', ('card.booking_trip_correction',))]
    events = [(tid, d) for tid, d in events if d.get('request_id') == applied_id]
    if not events:
        raise Refused('NOTHING_TO_REVERT')
    conn.execute('BEGIN IMMEDIATE')
    try:
        for tid, detail in events:
            row = policy._read(conn, {tid})[0]
            board = conn.execute('SELECT display_tab_id, revision, payload_json FROM board_rows WHERE row_id=?',
                                 ('card-' + tid,)).fetchone()
            after, before = detail['after'], detail['before']
            if (row['display_tab_id'], row['trip_id'], board[0]) != (after['display_tab_id'], after['trip_id'],
                                                                     after['display_tab_id']):
                raise Refused('CHANGED_SINCE_APPLY')
            fields = {k: before['transaction'][k] for k in policy.FIELDS}
            conn.execute('UPDATE transactions SET ' + ','.join(k + '=?' for k in fields) +
                         ',revision=revision+1 WHERE transaction_id=? AND revision=?',
                         (*fields.values(), tid, row['revision']))
            if before['ledger'] is not None:
                conn.execute('UPDATE ledger_entries SET display_tab_id=?, trip_id=? WHERE transaction_id=?',
                             (*before['ledger'], tid))
            payload = json.loads(board[2])
            payload.update(display_tab_id=before['board']['display_tab_id'],
                           classification_basis=fields['classification_basis'], revision=board[1] + 1)
            new_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,'
                         'created_at,client_request_id,kind) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         ('card-' + tid, board[1] + 1, board[2], new_payload, '', 'rule_change', ACTOR, utc_now(),
                          request_id + ':' + tid, 'revert'))
            conn.execute('UPDATE board_rows SET payload_json=?, display_tab_id=?, revision=revision+1'
                         ' WHERE row_id=? AND revision=?',
                         (new_payload, before['board']['display_tab_id'], 'card-' + tid, board[1]))
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                         (utc_now(), 'card.booking_trip_correction_revert', tid,
                          json.dumps({'request_id': request_id, 'reverts': applied_id, 'restored': before},
                                     ensure_ascii=False, sort_keys=True)))
        response = {'kind': 'revert', 'reverts': applied_id, 'written': len(events)}
        _store_request(conn, request_id, response, response)
        conn.execute('COMMIT')
    except BaseException:
        conn.rollback()
        raise
    return response


def _private_out(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT.resolve()):
        raise Refused('OUTPUT_INSIDE_REPOSITORY')
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _write_gate(host: Path, args):
    if args.isolated_copy:
        if host == LIVE_HOST.resolve():
            raise Refused('ISOLATED_COPY_REQUIRED')
        return
    from tools.core_rejudge import Refused as BackupRefused, require_backup
    try:
        require_backup(host, args.backup_evidence)
    except BackupRefused as exc:
        raise Refused(exc.code) from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='private output folder outside the repository')
    parser.add_argument('--snapshot-cache', type=Path, help='private pickle reused while OTA inputs are unchanged')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--revert', metavar='APPLIED_REQUEST_ID')
    parser.add_argument('--request-id')
    parser.add_argument('--expected-digest')
    parser.add_argument('--backup-evidence', type=Path)
    parser.add_argument('--isolated-copy', action='store_true', help='host is a copy; no backup gate')
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    try:
        out = _private_out(args.out)
        write = bool(args.apply or args.revert)
        if write:
            if not args.request_id:
                raise Refused('REQUEST_ID_REQUIRED')
            if args.apply and not args.expected_digest:
                raise Refused('PREVIEW_DIGEST_REQUIRED')
            _write_gate(host, args)
        configure(host)
        db = host / 'data/board.sqlite'
        with closing(sqlite3.connect(db.resolve().as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True,
                                     isolation_level=None, timeout=30)) as conn:
            if args.revert:
                result = revert(conn, out, applied_id=args.revert, request_id=args.request_id)
            else:
                current, key = snapshot(host, args.snapshot_cache)
                if args.apply:
                    result = apply(conn, host, current, out, request_id=args.request_id,
                                   expected_digest=args.expected_digest)
                else:
                    report, _, _ = preview(conn, host, current, out)
                    result = {'status': 'PREVIEW', 'digest': report['digest'], 'counts': report['counts']}
        print(json.dumps({'status': 'OK', **result}, ensure_ascii=False))
        return 0
    except Refused as exc:
        code = exc.code
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__
    print(json.dumps({'status': 'FAILED', 'code': code}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
