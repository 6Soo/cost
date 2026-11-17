"""Narrow, reversible correction of bulk record-batch owner confirmation stamps.

A record batch stamps confirmed_by='owner' on every projected card row without
a user decision. Only stamps proven to come from that batch shape are released
to 'automatic'; individual stamps and every manual signal stay protected.
Transactions, ledger entries, amounts, attribution and evidence never change.
"""
from collections import Counter
from datetime import date
import json

from .closed_period import manual_ids, trip_map
from .closed_period_repair import _financial_state
from .decision_provenance import _state, _digest
from .db import utc_now
from .quarter_costs import quarter_of

SCOPE = 'bulk_confirmation_provenance'
RELEASE = 'card.bulk_confirmation_provenance_corrected'
RESTORE = 'card.bulk_confirmation_provenance_restored'
MANUAL_SOURCES = {'user_decision', 'user_exception', 'owner_booking', 'manual',
                  'manual_hold', 'previous_decision'}
MANUAL_AUDIT_KINDS = ('trip_assignment.reviewed', 'card.region_assignment_corrected',
                      'card.trip_scope_policy_applied', 'card.booking_trip_correction')
MIN_SCOPE = (2026, 3)


def _in_scope(tab, valid, year, quarter):
    if tab == f'quarter:{year}:{quarter}':
        return True
    trip = valid.get(tab)
    if not trip or trip.get('deleted') or trip.get('archived') or trip.get('tab_kind', 'trip') != 'trip':
        return False
    try:
        return quarter_of(date.fromisoformat(trip['starts_on'])) == (year, quarter)
    except (KeyError, TypeError, ValueError):
        return False


def _stamp_index(conn):
    """First owner stamp per card row and per-minute batch sizes over the whole DB.

    A creation revision (prev_json='{}') counts as the first stamp: the record
    batch writes confirmed_by='owner' at projection time, not in a later edit.
    """
    stamps = {}
    for row_id, revision, event_id, change_mode, actor, created_at, kind in conn.execute(
            "SELECT row_id,revision,event_id,change_mode,actor,created_at,kind FROM board_revisions "
            "WHERE row_id LIKE 'card-%' AND json_extract(new_json,'$.confirmed_by')='owner' "
            "AND COALESCE(json_extract(prev_json,'$.confirmed_by'),'')!='owner' ORDER BY row_id,revision"):
        if row_id in stamps:
            continue
        stamps[row_id] = dict(revision=revision, minute=(created_at or '')[:16],
                              record_batch=(change_mode == 'exception' and actor == 'owner'
                                            and kind == 'save' and not event_id))
    batches = Counter(s['minute'] for s in stamps.values() if s['record_batch'])
    return stamps, batches


def _manual_history(conn):
    """Owner/authority history that outlives the batch stamp (owner decision 2026-11-13).

    A board revision is a signal unless it is automatic or the record-batch
    stamp shape itself; the repair family's own rule_change history is always
    actor='automatic', so apply/restore never protect a row from themselves.
    """
    board_rows = {r[0] for r in conn.execute(
        "SELECT DISTINCT row_id FROM board_revisions WHERE row_id LIKE 'card-%' "
        "AND actor!='automatic' AND NOT (actor='owner' AND change_mode='exception' "
        "AND kind='save' AND COALESCE(event_id,'')='')")}
    audit_ids = set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='change_log'").fetchone():
        audit_ids = {r[0] for r in conn.execute(
            "SELECT DISTINCT subject FROM change_log WHERE kind LIKE 'owner%' "
            "OR kind IN (" + ','.join('?' for _ in MANUAL_AUDIT_KINDS) + ')', MANUAL_AUDIT_KINDS)}
    return board_rows, audit_ids


def preview(conn, trips, *, year, quarter, min_batch=5):
    if not (isinstance(year, int) and isinstance(quarter, int)
            and 1 <= quarter <= 4 and (year, quarter) >= MIN_SCOPE):
        raise ValueError('INVALID_SCOPE')
    from .automatic_classification import _read
    valid, manual = trip_map(trips), manual_ids(conn)
    rows = {r['transaction_id']: r for r in _read(conn)}
    stamps, batches = _stamp_index(conn)
    manual_board_rows, manual_audit_ids = _manual_history(conn)
    quarter_id = f'quarter:{year}:{quarter}'
    excluded, targets, owner_rows = Counter(), [], 0
    manual_breakdown = Counter()
    for row_id, raw in conn.execute("SELECT row_id,payload_json FROM board_rows "
                                    "WHERE row_kind='expense' AND row_id LIKE 'card-%'"):
        payload = json.loads(raw)
        if payload.get('confirmed_by') != 'owner':
            continue
        tid = row_id[5:]
        row = rows.get(tid)
        if not row:
            continue
        attribution = row.get('display_tab_id') or row.get('trip_id') or ''
        if attribution in ('', 'unclassified') or not _in_scope(attribution, valid, year, quarter):
            continue
        owner_rows += 1
        reason = ''
        if tid in manual or row.get('decided_at') or row['classification_source'] in MANUAL_SOURCES:
            reason = 'MANUAL_OR_USER_EXCEPTION'
            manual_breakdown['existing_manual'] += 1
        elif row_id in manual_board_rows:
            reason = 'MANUAL_OR_USER_EXCEPTION'
            manual_breakdown['board_history'] += 1
        elif tid in manual_audit_ids:
            reason = 'MANUAL_OR_USER_EXCEPTION'
            manual_breakdown['audit_history'] += 1
        else:
            stamp = stamps.get(row_id)
            if not stamp:
                reason = 'NO_STAMP_REVISION'
            elif not stamp['record_batch']:
                reason = 'NOT_RECORD_BATCH'
            elif batches[stamp['minute']] < min_batch:
                reason = 'INDIVIDUAL_STAMP'
            elif row.get('duplicate_of') or row.get('conflict_reason') or row.get('parse_error'):
                reason = 'SOURCE_PROTECTED'
            elif conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=? AND source_hash=?',
                              (tid, row['source_hash'])).fetchone():
                reason = 'REVIEW_HOLD'
            elif conn.execute('SELECT 1 FROM transaction_company_exclusions '
                              'WHERE transaction_id=? AND source_hash=? AND excluded=1',
                              (tid, row['source_hash'])).fetchone():
                reason = 'COMPANY_EXCLUDED'
        if reason:
            excluded[reason] += 1
            continue
        stamp = stamps[row_id]
        targets.append(dict(tid=tid, row_id=row_id, attribution=attribution,
                            stamp=dict(revision=stamp['revision'], minute=stamp['minute'],
                                       batch_size=batches[stamp['minute']]),
                            before=_state(conn, tid)))
    targets.sort(key=lambda t: t['tid'])
    minutes = Counter(t['stamp']['minute'] for t in targets)
    per_trip = Counter(t['attribution'] for t in targets)
    summary = dict(owner_stamped_rows=owner_rows, to_correct=len(targets), excluded=dict(excluded),
                   manual_breakdown=dict(manual_breakdown),
                   stamp_minutes=[dict(minute=m, rows=n, batch_size=batches[m])
                                  for m, n in sorted(minutes.items())],
                   trip_corrections=[dict(trip=valid.get(tab, {}).get('display_key')
                                          or (f'{year}년 {quarter}분기 기타비용' if tab == quarter_id else tab),
                                          count=n) for tab, n in sorted(per_trip.items())])
    return dict(digest=_digest([targets, trips, dict(year=year, quarter=quarter, min_batch=min_batch),
                                _financial_state(conn)]),
                targets=targets, summary=summary)


def replay(conn, request_id):
    row = conn.execute('SELECT payload_sha256,response_json FROM requests WHERE request_id=? AND scope=?',
                       (request_id, SCOPE)).fetchone()
    return dict(digest=row[0], **json.loads(row[1])) if row else None


def _write_payload(conn, row_id, board, payload, request_id):
    """Existing board revision/audit column shape; attribution stays untouched."""
    payload['revision'] = board['revision'] + 1
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) '
                 'VALUES (?,?,?,?,?,?,?,?,?)',
                 (row_id, board['revision'] + 1, board['payload_json'], encoded,
                  '', 'rule_change', 'automatic', utc_now(), request_id))
    conn.execute('UPDATE board_rows SET payload_json=?,revision=revision+1 WHERE row_id=?', (encoded, row_id))
    # M6: 통합 장부도 같은 payload를 본다. 이 경로는 귀속을 바꾸지 않으므로
    # payload 전체를 그대로 옮겨 적는다.
    from webapp.ledger_store_records import sync_ledger_from_record
    sync_ledger_from_record(conn, dict(payload, row_id=row_id))


def apply(conn, expected, trips, *, request_id, year, quarter, min_batch=5):
    if not request_id or conn.in_transaction:
        raise ValueError('BULK_CONFIRMATION_REQUEST_OR_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        prior = replay(conn, request_id)
        if prior:
            if expected['digest'] != prior['digest']:
                raise ValueError('BULK_CONFIRMATION_REQUEST_CONFLICT')
            conn.rollback()
            return dict(prior, replay=True, applied_this_run=0)
        current = preview(conn, trips, year=year, quarter=quarter, min_batch=min_batch)
        if expected['digest'] != current['digest']:
            raise ValueError('BULK_CONFIRMATION_PREVIEW_STALE')
        financial = _financial_state(conn)
        for target in current['targets']:
            tid, board = target['tid'], target['before']['board']
            payload = json.loads(board['payload_json'])
            payload['confirmed_by'] = 'automatic'
            _write_payload(conn, target['row_id'], board, payload, request_id)
            detail = dict(request_id=request_id, before=target['before'], after=_state(conn, tid),
                          financial=financial, before_confirmed_by='owner', after_confirmed_by='automatic',
                          stamp=target['stamp'])
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                         (utc_now(), RELEASE, tid, json.dumps(detail, ensure_ascii=False, sort_keys=True)))
        if _financial_state(conn) != financial:
            raise ValueError('BULK_CONFIRMATION_FINANCIAL_CHANGED')
        result = dict(current['summary'], applied_this_run=len(current['targets']), replay=False)
        conn.execute('INSERT INTO requests(request_id,scope,payload_sha256,response_json,created_at) VALUES (?,?,?,?,?)',
                     (request_id, SCOPE, current['digest'], json.dumps(result, sort_keys=True), utc_now()))
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def restore_preview(conn, request_id):
    targets = []
    financial = _financial_state(conn)
    for entry, tid, raw in conn.execute('SELECT entry_id,subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id', (RELEASE,)):
        detail = json.loads(raw)
        if detail['request_id'] != request_id:
            continue
        if conn.execute("SELECT 1 FROM change_log WHERE kind=? AND json_extract(detail_json,'$.release_entry_id')=?", (RESTORE, entry)).fetchone():
            continue
        if _state(conn, tid) != detail['after']:
            raise ValueError('BULK_CONFIRMATION_RESTORE_STALE')
        if detail.get('financial', financial) != financial:
            raise ValueError('BULK_CONFIRMATION_RESTORE_FINANCIAL_STALE')
        targets.append(dict(entry=entry, tid=tid, detail=detail))
    return dict(digest=_digest([targets, financial]), targets=targets, summary=dict(restore=len(targets)))


def restore(conn, expected, request_id):
    if conn.in_transaction:
        raise ValueError('BULK_CONFIRMATION_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = restore_preview(conn, request_id)
        if current['digest'] != expected['digest']:
            raise ValueError('BULK_CONFIRMATION_PREVIEW_STALE')
        financial = _financial_state(conn)
        for target in current['targets']:
            tid, detail = target['tid'], target['detail']
            board = detail['before']['board']
            now = _state(conn, tid)['board']
            payload = json.loads(board['payload_json'])
            _write_payload(conn, 'card-' + tid, now, payload, 'restore-' + request_id)
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                         (utc_now(), RESTORE, tid, json.dumps(dict(release_entry_id=target['entry'], request_id=request_id))))
        if _financial_state(conn) != financial:
            raise ValueError('BULK_CONFIRMATION_FINANCIAL_CHANGED')
        conn.commit()
        return current['summary']
    except BaseException:
        conn.rollback()
        raise
