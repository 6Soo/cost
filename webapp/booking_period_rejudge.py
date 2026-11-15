"""Recorded lodging/flight attribution follows its verified booking period (TRIP-033, TRIP-036).

Each recorded row gets an evidence digest: source hash, OTA event, service period, the chosen trip with the
revisions of the chosen and current trip tabs, and the policy version. Only a row whose digest differs from the last
one stored is judged again, and the worker computes digests only when the OTA reconciliation generation changes;
reading and restarting do not correct anything (TRIP-035). A row without a stored digest gets one as its baseline.
Real manual corrections, owner bookings, holds, exclusions, duplicates, refund pairs and source conflicts stay.
Transaction, ledger entry, board row, revision and history change in one transaction.
"""
from __future__ import annotations

import hashlib
import json

from app import automatic_classification as policy

SCOPE = 'booking_period_digest'
CORRECTION_KIND = 'card.booking_trip_correction'
ITEMS = ('숙박비', '항공료')
HUMAN_SOURCES = ('user_decision', 'user_exception', 'owner_booking', 'manual', 'manual_hold')


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def digest_key(tid) -> str:
    return 'booking-period-digest:' + tid


def stored_digests(conn) -> dict:
    return {r[0][len('booking-period-digest:'):]: r[1] for r in conn.execute(
        'SELECT request_id, payload_sha256 FROM requests WHERE scope=?', (SCOPE,))}


def store_digest(conn, tid, digest, detail):
    from app.db import utc_now
    conn.execute('INSERT INTO requests VALUES (?,?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET'
                 ' payload_sha256=excluded.payload_sha256, response_json=excluded.response_json,'
                 ' created_at=excluded.created_at WHERE requests.scope=excluded.scope',
                 (digest_key(tid), SCOPE, digest, json.dumps(detail, ensure_ascii=False, sort_keys=True), utc_now()))


def recorded_rows(conn) -> set:
    """Recorded lodging/flight purchases (a board row exists)."""
    return {r[0] for r in conn.execute(
        "SELECT t.transaction_id FROM transactions t WHERE t.item IN (?,?) AND t.transaction_direction='purchase'"
        " AND t.amount_krw>0 AND EXISTS(SELECT 1 FROM board_rows b WHERE b.row_id='card-'||t.transaction_id)",
        ITEMS)}


def protection(conn, row, manual) -> str:
    """Why the row must stay where it is, or ''. `manual` is `closed_period.manual_ids`."""
    tid = row['transaction_id']
    if (tid in manual or row.get('decided_at') is not None
            or row.get('classification_source') in HUMAN_SOURCES):
        return 'MANUAL'
    if row.get('classification_source') in ('ai_inference', 'refund_original'):
        return 'P2_OR_REFUND_ORIGINAL'
    if any(row.get(k) for k in ('parse_error', 'duplicate_of', 'conflict_reason')):
        return 'SOURCE_PROTECTED'
    if conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=?', (tid,)).fetchone():
        return 'HOLD'
    if conn.execute('SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=? AND excluded=1',
                    (tid,)).fetchone():
        return 'EXCLUDED'
    if conn.execute("SELECT 1 FROM transactions WHERE issuer=? AND card_tail=? AND original_approval_number=?"
                    " AND COALESCE(original_approval_number,'')!=''"
                    " AND (transaction_direction IN ('cancellation','refund') OR amount_krw<0) LIMIT 1",
                    (row['issuer'], row['card_tail'], row['approval_number'])).fetchone():
        return 'REFUND_PAIR'
    return ''


def _current(conn, tid, row):
    board = conn.execute('SELECT display_tab_id, revision, payload_json FROM board_rows WHERE row_id=?',
                         ('card-' + tid,)).fetchone()
    ledger = conn.execute('SELECT display_tab_id, trip_id FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()
    tab = (board[0] if board else '') or row.get('display_tab_id') or row.get('trip_id') or ''
    return tab, board, ledger


def _overlaps(trip, period, service, handover):
    from app.reconciliation import overlaps_stay
    return bool(trip and trip.get('starts_on') and trip.get('ends_on') and overlaps_stay(
        trip['starts_on'], trip['ends_on'], period['starts_on'], period['ends_on'], service=service, handover=handover))


def assess(flow, current, *, include_archived=False, selected=None):
    """One record per recorded row with a verified booking period. Reads only."""
    from app.closed_period import manual_ids
    from app.reconciliation import handover_days
    from .card_classification_completion import verified_booking_facts
    conn = flow.board.conn
    manual = manual_ids(conn)
    selected = recorded_rows(conn) if selected is None else selected
    checked, blocked = verified_booking_facts(flow, current, selected)
    trips = {t['tab_id']: t for t in flow.board.list_trips(include_archived=True)}
    handover = handover_days([t for t in trips.values() if not t.get('archived')])
    found = {}
    for tid, fact, row, event in checked:
        period = {k: fact['period'][k] for k in ('starts_on', 'ends_on')}
        service = fact.get('item') != '숙박비'
        chosen = flow.booking_trip(row, dict(period, service=service), include_archived=include_archived) or ''
        tab, board, ledger = _current(conn, tid, row)
        from app.ledger import REFUND_TAB
        record = dict(
            transaction_id=tid, item=row.get('item') or '', period=period, service=service,
            current_tab=tab, chosen_trip=chosen, current_is_trip=tab in trips,
            current_overlaps=_overlaps(trips.get(tab), period, service, handover),
            current_archived=bool((trips.get(tab) or {}).get('archived')),
            chosen_archived=bool((trips.get(chosen) or {}).get('archived')),
            protection='REFUND_TAB' if tab == REFUND_TAB else protection(conn, row, manual),
            source_hash=row['source_hash'],
            ota_event_id=str(fact.get('ota_event_id') or ''), revision=row['revision'],
            board_revision=board[1] if board else None)
        record['digest'] = _sha([
            row['source_hash'], record['ota_event_id'],
            [event.get(k) for k in ('event_type', 'status', 'refund_status', 'amount', 'currency')],
            period, fact.get('item'), chosen,
            [(t, (trips.get(t) or {}).get('revision'), (trips.get(t) or {}).get('starts_on'),
              (trips.get(t) or {}).get('ends_on')) for t in sorted({chosen, tab})],
            policy.POLICY])
        if tid in found and (found[tid]['chosen_trip'], found[tid]['period']) != (chosen, period):
            blocked.add(tid)
        found[tid] = record
    return [found[tid] for tid in sorted(found) if tid not in blocked]


def correct(conn, record, *, request_id, actor='automatic'):
    """Move one recorded row to `record['chosen_trip']` atomically with its history. Caller holds the transaction."""
    from app.db import utc_now
    tid, trip = record['transaction_id'], record['chosen_trip']
    row = policy._read(conn, {tid})[0]
    if row['revision'] != record['revision'] or row['source_hash'] != record['source_hash']:
        raise ValueError('BOOKING_TRIP_CORRECTION_STALE')
    tab, board, ledger = _current(conn, tid, row)
    if board is None or board[1] != record['board_revision']:
        raise ValueError('BOOKING_TRIP_CORRECTION_STALE')
    period = record['period']
    basis = f"예약 이용기간 근거 우선: 검증된 예약 이용기간 {period['starts_on']}~{period['ends_on']} · 기록 귀속 교정"
    payload = json.loads(board[2])
    before = {'transaction': {k: row[k] for k in (*policy.FIELDS, 'revision')},
              'ledger': list(ledger) if ledger else None,
              'board': {'display_tab_id': board[0], 'revision': board[1],
                        'classification_basis': payload.get('classification_basis')}}
    conn.execute('UPDATE transactions SET display_tab_id=?, trip_id=?, classification_basis=?, revision=revision+1'
                 ' WHERE transaction_id=? AND revision=?', (trip, trip, basis, tid, row['revision']))
    conn.execute('UPDATE ledger_entries SET display_tab_id=?, trip_id=? WHERE transaction_id=?', (trip, trip, tid))
    old_payload = board[2]
    payload.update(display_tab_id=trip, classification_basis=basis, revision=board[1] + 1)
    new_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,'
                 'client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                 ('card-' + tid, board[1] + 1, old_payload, new_payload, '', 'rule_change', actor, utc_now(),
                  request_id + ':' + tid))
    cursor = conn.execute('UPDATE board_rows SET payload_json=?, display_tab_id=?, revision=revision+1'
                          ' WHERE row_id=? AND revision=?', (new_payload, trip, 'card-' + tid, board[1]))
    if cursor.rowcount != 1:
        raise ValueError('BOOKING_TRIP_CORRECTION_STALE')
    after = {'display_tab_id': trip, 'trip_id': trip, 'classification_basis': basis}
    conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                 (utc_now(), CORRECTION_KIND, tid, json.dumps(
                     {'request_id': request_id, 'actor': actor, 'before': before, 'after': after,
                      'trip_id': trip, 'basis': basis, 'digest': record['digest']},
                     ensure_ascii=False, sort_keys=True)))
    store_digest(conn, tid, record['digest'], {'trip_id': trip, 'request_id': request_id})


def rejudge(flow, current, *, request_id):
    """Worker step after a new OTA generation: correct rows whose evidence digest changed. Returns counts."""
    conn = flow.board.conn
    from app.closed_period import excluded
    trips = list(flow.board.list_trips())
    stored = stored_digests(conn)
    records = assess(flow, current)
    counts = {'assessed': len(records), 'baselined': 0, 'corrected': 0, 'kept': 0}
    nested = conn.in_transaction
    conn.execute('SAVEPOINT booking_period_rejudge' if nested else 'BEGIN IMMEDIATE')
    try:
        for record in records:
            tid = record['transaction_id']
            previous = stored.get(tid)
            if previous == record['digest']:
                continue
            row = policy._read(conn, {tid})[0]
            movable = (previous is not None and record['chosen_trip']
                       and record['chosen_trip'] != record['current_tab'] and not record['protection']
                       and not record['current_archived'] and not excluded(row, trips))
            if movable:
                correct(conn, record, request_id=request_id)
                counts['corrected'] += 1
            else:
                store_digest(conn, tid, record['digest'], {'trip_id': record['current_tab'],
                                                           'request_id': request_id})
                counts['baselined' if previous is None else 'kept'] += 1
        conn.execute('RELEASE SAVEPOINT booking_period_rejudge' if nested else 'COMMIT')
    except BaseException:
        if nested:
            conn.execute('ROLLBACK TO SAVEPOINT booking_period_rejudge')
            conn.execute('RELEASE SAVEPOINT booking_period_rejudge')
        else:
            conn.rollback()
        raise
    return counts
