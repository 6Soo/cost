"""Reversible PROC-072 grouping of completed cards incorrectly in open ledgers."""
from collections import Counter
import json
from types import SimpleNamespace

from .closed_period import completed_period, completed_trip, exception_trip, manual_ids, open_trip, trip_map
from .decision_provenance import _state, _digest
from .db import utc_now

SCOPE = 'closed_period_grouping'
RELEASE = 'card.closed_period_grouped'
RESTORE = 'card.closed_period_restored'
FIELDS = ('item', 'display_tab_id', 'trip_id')


def _sync(conn, tid, values, request_id, *, old_board=None):
    conn.execute('UPDATE ledger_entries SET '+','.join(k+'=?' for k in FIELDS)+' WHERE transaction_id=?',
                 (*[values[k] for k in FIELDS],tid))
    board = _state(conn,tid)['board']
    if not board:
        return
    payload = json.loads((old_board or board)['payload_json'])
    if old_board is None:
        payload.update(values)
    payload['revision'] = board['revision']+1
    encoded = json.dumps(payload,ensure_ascii=False,sort_keys=True)
    tab = old_board['display_tab_id'] if old_board else values['display_tab_id']
    conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
        ('card-'+tid,board['revision']+1,board['payload_json'],encoded,'','rule_change','automatic',utc_now(),request_id))
    conn.execute('UPDATE board_rows SET payload_json=?,display_tab_id=?,revision=revision+1 WHERE row_id=?',
                 (encoded,tab,'card-'+tid))


def _open_destination(value, valid):
    from .classification_correction import _open_p2_tab
    return _open_p2_tab(list(valid.values()), value)


def preview(conn, trips, *, evidence=None):
    from .automatic_classification import _read
    from .review import correction_protection_reason
    from .partial_refund import refund_links
    valid, manual = trip_map(trips), manual_ids(conn)
    rows = _read(conn)
    closed = [r for r in rows if completed_period(r)]
    linked = refund_links(conn, [r['transaction_id'] for r in rows])
    refund_group = set(linked) | {v['original_id'] for v in linked.values()}
    counts, excluded, distribution, moves, targets = Counter(), Counter(), Counter(), Counter(), []
    for row in closed:
        tid = row['transaction_id']
        counts['completed_total'] += 1
        if any(completed_trip(valid.get(row.get(k))) for k in ('trip_id','display_tab_id')):
            counts['completed_trip_unchanged'] += 1
            excluded['COMPLETED_TRIP'] += 1
            continue
        destinations = {row.get(k) for k in ('trip_id','display_tab_id')} - {None, '', 'unclassified'}
        opened = {v for v in destinations if _open_destination(v, valid)}
        if not opened:
            excluded['OUTSIDE_OPEN_DESTINATION'] += 1
            continue
        counts['in_open_destinations'] += 1
        for value in sorted(opened):
            distribution[value] += 1
        state = _state(conn, tid)
        is_manual = tid in manual or bool(row.get('decided_at')) or row['classification_source'] in {
            'user_decision','user_exception','owner_booking','manual','manual_hold'}
        if exception_trip(row, trips, evidence=(evidence or {}).get(tid), manual=tid in manual):
            counts['confirmed_exceptions'] += 1
            excluded['CONFIRMED_OPEN_EXCEPTION'] += 1
            continue
        reason = 'MANUAL_OR_UNVERIFIED_PROVENANCE' if is_manual else ''
        if not reason:
            reason = correction_protection_reason(SimpleNamespace(conn=conn), tid, row['source_hash'])
        if not reason and tid in refund_group:
            reason = 'REFUND_GROUP'
        if not reason and len(destinations) != 1:
            reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
        for projection in (state['ledger'], state['board']):
            if projection and not reason:
                if projection.get('display_tab_id') not in destinations:
                    reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
                if projection is state['ledger'] and projection.get('trip_id') not in destinations:
                    reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
        if reason:
            excluded[reason] += 1
            continue
        day = row['approval_date'] or row['posting_date']
        quarter = (int(day[5:7])-1)//3+1
        target = f'quarter:{day[:4]}:{quarter}'
        item = '2025년 항목' if completed_period(row) == '2025' else '분기 기타비용'
        values = dict(item=item, display_tab_id=target, trip_id='')
        targets.append(dict(tid=tid, before=state, values=values))
        moves[completed_period(row)] += 1
    summary = dict(counts, move_2025=moves['2025'], move_2026Q1=moves['2026Q1'],
                   to_move=len(targets), excluded=dict(excluded),
                   open_distribution=[dict(trip=valid.get(k,{}).get('display_key') or k, count=n)
                                      for k,n in sorted(distribution.items())],
                   open_trip_row_delta=[dict(trip=t.get('display_key') or k,
                       delta=-sum(x['before']['transaction']['trip_id']==k for x in targets))
                       for k,t in sorted(valid.items()) if open_trip(t)])
    return dict(digest=_digest([targets, trips, evidence or {}]), targets=targets, summary=summary)


def replay(conn, request_id):
    row = conn.execute('SELECT payload_sha256,response_json FROM requests WHERE request_id=? AND scope=?',
                       (request_id,SCOPE)).fetchone()
    return dict(digest=row[0], **json.loads(row[1])) if row else None


def apply(conn, expected, trips, *, request_id, evidence=None):
    if not request_id or conn.in_transaction:
        raise ValueError('GROUPING_REQUEST_OR_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        prior = replay(conn,request_id)
        if prior:
            if expected['digest'] != prior['digest']:
                raise ValueError('GROUPING_REQUEST_CONFLICT')
            conn.rollback()
            return dict(prior, replay=True, applied_this_run=0)
        current = preview(conn,trips,evidence=evidence)
        if expected['digest'] != current['digest']:
            raise ValueError('GROUPING_PREVIEW_STALE')
        for target in current['targets']:
            tid, values = target['tid'], target['values']
            conn.execute('UPDATE transactions SET '+','.join(k+'=?' for k in FIELDS)+
                         ',revision=revision+1 WHERE transaction_id=?', (*[values[k] for k in FIELDS],tid))
            _sync(conn,tid,values,request_id)
            detail = dict(request_id=request_id, before=target['before'], after=_state(conn,tid))
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(),RELEASE,tid,json.dumps(detail,ensure_ascii=False,sort_keys=True)))
        result = dict(current['summary'], applied_this_run=len(current['targets']))
        conn.execute('INSERT INTO requests(request_id,scope,payload_sha256,response_json,created_at) VALUES (?,?,?,?,?)',
            (request_id,SCOPE,current['digest'],json.dumps(result,sort_keys=True),utc_now()))
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def restore_preview(conn, request_id):
    targets = []
    for entry,tid,raw in conn.execute('SELECT entry_id,subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id', (RELEASE,)):
        detail = json.loads(raw)
        if detail['request_id'] != request_id:
            continue
        if conn.execute("SELECT 1 FROM change_log WHERE kind=? AND json_extract(detail_json,'$.release_entry_id')=?",(RESTORE,entry)).fetchone():
            continue
        if _state(conn,tid) != detail['after']:
            raise ValueError('GROUPING_RESTORE_STALE')
        targets.append(dict(entry=entry,tid=tid,detail=detail))
    return dict(digest=_digest(targets),targets=targets,summary=dict(restore=len(targets)))


def restore(conn, expected, request_id):
    if conn.in_transaction:
        raise ValueError('GROUPING_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = restore_preview(conn,request_id)
        if current['digest'] != expected['digest']:
            raise ValueError('GROUPING_PREVIEW_STALE')
        for target in current['targets']:
            tid, old = target['tid'], target['detail']['before']
            conn.execute('UPDATE transactions SET '+','.join(k+'=?' for k in FIELDS)+
                         ',revision=revision+1 WHERE transaction_id=?',(*[old['transaction'][k] for k in FIELDS],tid))
            _sync(conn,tid,old['ledger'] or old['transaction'],'restore-'+request_id,old_board=old['board'])
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(),RESTORE,tid,json.dumps(dict(release_entry_id=target['entry'],request_id=request_id))))
        conn.commit()
        return current['summary']
    except BaseException:
        conn.rollback()
        raise
