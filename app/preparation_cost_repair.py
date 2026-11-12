"""Conservative, reversible removal of proven generic preparation assignments."""
from collections import Counter
import json
from types import SimpleNamespace
from .closed_period import completed_period, manual_ids, open_trip, trip_map
from .closed_period_repair import _financial_state, _complete_refund_groups, _sync
from .decision_provenance import _state, _digest
from .db import utc_now

SCOPE = 'preparation_cost_grouping'
RELEASE = 'card.preparation_cost_grouped'
RESTORE = 'card.preparation_cost_restored'
FIELDS = ('item', 'display_tab_id', 'trip_id', 'classification_basis')


def preview(conn, trips, *, evidence=None):
    from .automatic_classification import _read
    from .provisional_assignment import card_trip_candidates, canonical_trip_periods
    from .review import correction_protection_reason
    from .partial_refund import refund_links
    from .rules import list_rules, rule_matches
    from .db import Store
    from .classification_provenance import CODE_SOURCES
    valid, manual = trip_map(trips), manual_ids(conn)
    canonical = canonical_trip_periods(trips)
    rows = _read(conn)
    by_id = {r['transaction_id']: r for r in rows}
    linked = refund_links(conn, list(by_id))
    groups = _complete_refund_groups(conn, rows, linked)
    group_ids = set().union(*groups.values()) if groups else set()
    rules = list_rules(Store(conn, schema_policy='require'))
    excluded, distribution, quarters = Counter(), Counter(), Counter()
    pending, opened, proven = {}, 0, 0
    for row in rows:
        tid = row['transaction_id']
        destinations = {row.get(k) for k in ('trip_id','display_tab_id')} - {None, '', 'unclassified'}
        if not any(open_trip(valid.get(v)) for v in destinations):
            continue
        opened += 1
        basis = row.get('classification_basis') or ''
        is_preparation = '다음 여행 준비기간 · ' in basis
        if is_preparation:
            proven += 1
            distribution[row.get('trip_id') or row.get('display_tab_id')] += 1
        reason = ''
        if completed_period(row):
            reason = 'CLOSED_CARD_PERIOD'
        elif tid in manual or row.get('decided_at') or row['classification_source'] in {
                'user_decision','user_exception','owner_booking','manual','manual_hold'}:
            reason = 'MANUAL_OR_USER_EXCEPTION'
        elif row['classification_source'] not in CODE_SOURCES or not is_preparation:
            reason = 'UNPROVEN_PREPARATION'
        elif any(word in basis for word in ('예약', '이용기간', 'P2_METADATA', '사용자 규칙', '사용자 예외')) or (evidence or {}).get(tid):
            reason = 'RESERVATION_OR_EXCEPTION_EVIDENCE'
        elif any(rule_matches(rule, row)[0] and (
                rule.get('optional', {}).get('inferred_assignment')
                or any(k in rule.get('effects', {}) for k in ('trip_id','display_tab_id'))
                or rule.get('origin') in {'owner-ota-booking','auto-ota-period','ota-mail-live',
                                          'ota-portal-live','guide-airfare-live'}) for rule in rules):
            reason = 'ACTIVE_RULE_EVIDENCE'
        elif card_trip_candidates(row, list(canonical.values())):
            reason = 'ENCLOSING_PERIOD_OR_EXCEPTION'
        else:
            reason = correction_protection_reason(SimpleNamespace(conn=conn), tid, row['source_hash']) or ''
            if reason in {'CANCELLATION_OR_REFUND','ORIGINAL_WITH_REFUND'} and tid in group_ids:
                reason = ''  # All members and the raw financial graph are checked below.
            # The shared cancellation guard returns before hold/exclusion checks.
            if not reason and conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=?', (tid,)).fetchone():
                reason = 'REVIEW_HOLD'
            if not reason and conn.execute('SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=? AND excluded=1', (tid,)).fetchone():
                reason = 'COMPANY_EXCLUDED'
        state = _state(conn, tid)
        if not reason and (len(destinations) != 1 or row.get('trip_id') not in canonical):
            reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
        for projection in (state['ledger'], state['board']):
            if not projection or reason:
                continue
            if projection.get('display_tab_id') not in destinations:
                reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
            if projection is state['ledger'] and projection.get('trip_id') not in destinations:
                reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
            if projection is state['board']:
                payload = json.loads(projection['payload_json'])
                if (any(k in payload and payload[k] not in destinations for k in ('trip_id','display_tab_id'))
                        or payload.get('confirmed_by') not in (None, '', 'automatic')):
                    reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
        from .card_destination import observed_quarter
        quarter = observed_quarter(row)
        if not reason and (not row.get('approval_date') or not quarter):
            reason = 'DATE_UNPROVEN'
        if reason:
            excluded[reason] += 1
            continue
        pending[tid] = dict(tid=tid, before=state,
                           values=dict(item='분기 기타비용', trip_id='', display_tab_id=quarter[0],
                                       classification_basis='PROC-004 · TRIP-043 · DATE-040 · 일반 준비기간 추론 폐지 · 결제일 분기 기타비용'))
    moved_groups, refund_moved = 0, 0
    for original, members in groups.items():
        candidates = members & pending.keys()
        if not candidates:
            continue
        group_links = [linked[tid] for tid in members if tid in linked]
        reason = ''
        if not members <= pending.keys():
            reason = 'INELIGIBLE_MEMBER'
        elif (not group_links or any(l.get('inferred') or l.get('status') not in ('full','partial')
                                     or l.get('net_krw', -1) < 0 for l in group_links)):
            reason = 'UNVERIFIED_OR_EXCESS'
        elif {l['original_id'] for l in group_links} != {original} or members != {original} | {tid for tid in members if tid in linked}:
            reason = 'INCOMPLETE_GROUP'
        if reason:
            for tid in candidates:
                pending.pop(tid)
            excluded['REFUND_'+reason] += len(candidates)
        else:
            # Refunds follow the original's quarter, never independently split a group.
            tab = pending[original]['values']['display_tab_id']
            for tid in members:
                pending[tid]['values']['display_tab_id'] = tab
            moved_groups += 1
            refund_moved += len(members)
    targets = [pending[k] for k in sorted(pending)]
    deltas = []
    for k,t in sorted(valid.items()):
        if not open_trip(t):
            continue
        moved = [x for x in targets if x['before']['transaction']['trip_id']==k]
        deltas.append(dict(trip=t.get('display_key') or k, delta=-len(moved),
            ledger_delta=-sum(bool(x['before']['ledger']) for x in moved),
            board_delta=-sum(bool(x['before']['board']) for x in moved)))
    for target in targets:
        quarters[target['values']['display_tab_id']] += 1
    summary = dict(open_trip_rows=opened, proven_preparation_rows=proven, to_move=len(targets),
        preserved=opened-len(targets), excluded=dict(excluded),
        refund_move_rows=refund_moved, refund_move_groups=moved_groups,
        preparation_distribution=[dict(trip=valid.get(k,{}).get('display_key') or k,count=n)
                                  for k,n in distribution.most_common()],
        quarter_increases=dict(quarters), open_trip_row_delta=deltas)
    return dict(digest=_digest([targets,trips,evidence or {},_financial_state(conn),rules]),
                targets=targets,summary=summary)


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
