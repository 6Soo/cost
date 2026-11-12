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


def _financial_state(conn):
    """Bind and verify the existing refund graph, nets and protection records."""
    from .partial_refund import refund_links
    ids = [r[0] for r in conn.execute('SELECT transaction_id FROM transactions')]
    names = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                   if 'refund' in r[0] or r[0] in {
                       'transaction_review_holds', 'transaction_company_exclusions'})
    tables = {name: sorted(conn.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall(),
                           key=lambda row: json.dumps(row,sort_keys=True)) for name in names}
    return _digest(dict(links=refund_links(conn,ids),tables=tables))


def _refund_group_reason(conn, members, rows, pending, links, manual, trips, evidence):
    """Both sides must qualify; this never authorizes ordinary refund editing."""
    valid = trip_map(trips)
    for tid in sorted(members):
        row = rows.get(tid)
        if not row or not completed_period(row):
            return 'OPEN_PERIOD_MEMBER'
        if (tid in manual or row.get('decided_at') or row['classification_source'] in {
                'user_decision','user_exception','owner_booking','manual','manual_hold'}):
            return 'MANUAL_MEMBER'
        if any(completed_trip(valid.get(row.get(k))) for k in ('trip_id','display_tab_id')):
            return 'COMPLETED_TRIP_MEMBER'
        if exception_trip(row,trips,evidence=evidence.get(tid)):
            return 'CONFIRMED_OPEN_MEMBER'
        if row.get('parse_error') or row.get('duplicate_of') or row.get('conflict_reason'):
            return 'SOURCE_PROTECTED_MEMBER'
        if conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=? AND source_hash=?',
                        (tid,row['source_hash'])).fetchone():
            return 'REVIEW_HOLD_MEMBER'
        if conn.execute('SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=? AND source_hash=? AND excluded=1',
                        (tid,row['source_hash'])).fetchone():
            return 'COMPANY_EXCLUDED_MEMBER'
    group_links = [links[tid] for tid in members if tid in links]
    if any(link.get('status') == 'excess' or link['net_krw'] < 0 for link in group_links):
        return 'EXCESS_REFUND'
    if any(link.get('inferred') for link in group_links):
        return 'INFERRED_LINK'
    if not group_links or any(link.get('status') not in ('full','partial') for link in group_links):
        return 'UNVERIFIED_LINK'
    originals = {link['original_id'] for link in group_links}
    if len(originals) != 1 or members != originals | {tid for tid in members if tid in links}:
        return 'INCOMPLETE_OR_AMBIGUOUS_GROUP'
    if not members <= pending.keys():
        return 'INELIGIBLE_MEMBER'
    return ''


def _complete_refund_groups(conn, rows, linked):
    """The clean financial graph alone cannot prove a group's completeness."""
    from .partial_refund import _foreign_amount, _day, _settings
    by_id = {r['transaction_id']:r for r in rows}
    groups = {}
    for tid,link in linked.items():
        groups.setdefault(link['original_id'],{link['original_id']}).add(tid)
    for original,members in groups.items():
        row = by_id[original]
        number = str(row.get('approval_number') or '').strip()
        if number:
            for other in rows:
                if (other.get('issuer'),other.get('card_tail')) != (row.get('issuer'),row.get('card_tail')):
                    continue
                if (str(other.get('original_approval_number') or '').strip() == number
                        or str(other.get('approval_number') or '').strip() == number):
                    members.add(other['transaction_id'])
    # Foreign exact pairing also filters source-protected originals/refunds.
    # Keep its existing key/window; include protected candidates conservatively.
    window = int(_settings()['max_days_after_purchase'])
    def key(row):
        return (row.get('issuer'),row.get('card_tail'),row.get('merchant_normalized'),
                str(row.get('foreign_currency') or '').strip().upper(),_foreign_amount(row.get('foreign_amount')))
    def day(row):
        return _day(row.get('approval_date') or row.get('posting_date'))
    for original,members in groups.items():
        foreign_refunds = [tid for tid,link in linked.items() if tid in members
                           and link.get('basis')=='merchant_card_foreign_amount']
        if not foreign_refunds:
            continue
        original_row = by_id[original]
        when,foreign_key = day(original_row),key(original_row)
        refund_days = [day(by_id[tid]) for tid in foreign_refunds]
        for other in rows:
            if not (other.get('parse_error') or other.get('duplicate_of') or other.get('conflict_reason')):
                continue
            if key(other) != foreign_key:
                continue
            observed = day(other)
            # The normal pool drops unknown dates. They cannot establish that
            # a source-protected candidate is outside this group's window.
            relevant = observed is None or when is None
            if not relevant:
                relevant = (any(rday is None or 0 <= (rday-observed).days <= window for rday in refund_days)
                            if other.get('transaction_direction')=='purchase'
                            else 0 <= (observed-when).days <= window)
            if relevant:
                members.add(other['transaction_id'])
    return groups


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
    groups = _complete_refund_groups(conn,rows,linked)
    refund_group = set().union(*groups.values()) if groups else set()
    counts = Counter(completed_total=0,completed_trip_unchanged=0,in_open_destinations=0,confirmed_exceptions=0)
    excluded, distribution, moves, targets = Counter(), Counter(), Counter(), []
    pending_refunds = {}
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
        group_candidate = reason in {'REFUND_GROUP','CANCELLATION_OR_REFUND','ORIGINAL_WITH_REFUND'}
        if group_candidate:
            reason = ''  # Group checks below preserve every other protection.
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
        target = dict(tid=tid, before=state, values=values)
        if group_candidate:
            pending_refunds[tid] = target
        else:
            targets.append(target)
    by_id = {r['transaction_id']:r for r in rows}
    processed, refund_kept, refund_moved, moved_groups = set(), Counter(), 0, 0
    for tid in sorted(pending_refunds):
        original = linked[tid]['original_id'] if tid in linked else tid if tid in groups else next(
            (key for key,members in groups.items() if tid in members),None)
        if original is None:
            refund_kept['UNPAIRED'] += 1
            continue
        if original in processed:
            continue
        processed.add(original)
        members = groups[original]
        reason = _refund_group_reason(conn,members,by_id,pending_refunds,linked,manual,trips,evidence or {})
        if reason:
            refund_kept[reason] += len(members & pending_refunds.keys())
        else:
            targets.extend(pending_refunds[member] for member in sorted(members))
            refund_moved += len(members)
            moved_groups += 1
    for reason, count in refund_kept.items():
        excluded['REFUND_'+reason] += count
    for target in targets:
        moves[completed_period(target['before']['transaction'])] += 1
    summary = dict(counts, move_2025=moves['2025'], move_2026Q1=moves['2026Q1'],
                   to_move=len(targets), excluded=dict(excluded),
                   refund_candidate_rows=len(pending_refunds), refund_move_rows=refund_moved,
                   refund_move_groups=moved_groups, refund_preserved_rows=sum(refund_kept.values()),
                   refund_preserved=dict(refund_kept),
                   open_distribution=[dict(trip=valid.get(k,{}).get('display_key') or k, count=n)
                                      for k,n in sorted(distribution.items())],
                   open_trip_row_delta=[dict(trip=t.get('display_key') or k,
                       delta=-sum(x['before']['transaction']['trip_id']==k for x in targets),
                       ledger_delta=-sum(bool(x['before']['ledger']) and x['before']['ledger']['trip_id']==k for x in targets),
                       board_delta=-sum(bool(x['before']['board']) and x['before']['board']['display_tab_id']==k for x in targets))
                       for k,t in sorted(valid.items()) if open_trip(t)])
    return dict(digest=_digest([targets, trips, evidence or {}, _financial_state(conn)]), targets=targets, summary=summary)


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
        financial = _financial_state(conn)
        for target in current['targets']:
            tid, values = target['tid'], target['values']
            conn.execute('UPDATE transactions SET '+','.join(k+'=?' for k in FIELDS)+
                         ',revision=revision+1 WHERE transaction_id=?', (*[values[k] for k in FIELDS],tid))
            _sync(conn,tid,values,request_id)
            detail = dict(request_id=request_id, before=target['before'], after=_state(conn,tid),financial=financial)
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(),RELEASE,tid,json.dumps(detail,ensure_ascii=False,sort_keys=True)))
        if _financial_state(conn) != financial:
            raise ValueError('GROUPING_FINANCIAL_CHANGED')
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
    financial = _financial_state(conn)
    for entry,tid,raw in conn.execute('SELECT entry_id,subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id', (RELEASE,)):
        detail = json.loads(raw)
        if detail['request_id'] != request_id:
            continue
        if conn.execute("SELECT 1 FROM change_log WHERE kind=? AND json_extract(detail_json,'$.release_entry_id')=?",(RESTORE,entry)).fetchone():
            continue
        if _state(conn,tid) != detail['after']:
            raise ValueError('GROUPING_RESTORE_STALE')
        if detail.get('financial',financial) != financial:
            raise ValueError('GROUPING_RESTORE_FINANCIAL_STALE')
        targets.append(dict(entry=entry,tid=tid,detail=detail))
    return dict(digest=_digest([targets,financial]),targets=targets,summary=dict(restore=len(targets)))


def restore(conn, expected, request_id):
    if conn.in_transaction:
        raise ValueError('GROUPING_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = restore_preview(conn,request_id)
        if current['digest'] != expected['digest']:
            raise ValueError('GROUPING_PREVIEW_STALE')
        financial = _financial_state(conn)
        for target in current['targets']:
            tid, old = target['tid'], target['detail']['before']
            conn.execute('UPDATE transactions SET '+','.join(k+'=?' for k in FIELDS)+
                         ',revision=revision+1 WHERE transaction_id=?',(*[old['transaction'][k] for k in FIELDS],tid))
            _sync(conn,tid,old['ledger'] or old['transaction'],'restore-'+request_id,old_board=old['board'])
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(),RESTORE,tid,json.dumps(dict(release_entry_id=target['entry'],request_id=request_id))))
        if _financial_state(conn) != financial:
            raise ValueError('GROUPING_FINANCIAL_CHANGED')
        conn.commit()
        return current['summary']
    except BaseException:
        conn.rollback()
        raise
