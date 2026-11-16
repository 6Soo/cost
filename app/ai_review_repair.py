"""Manifest-driven AI quarter-review corrections: preview, gated apply, audited restore.

The private manifest selects the rows; every protection of the preparation-cost
repair still applies. No source text, amount, sign, id or financial link changes,
no new ledger row is created, and no user-decision marker is written.
"""
from collections import Counter
import json
import re
from types import SimpleNamespace
from .closed_period import completed_period, manual_ids, open_trip, trip_map
from .closed_period_repair import _financial_state, _complete_refund_groups, _open_destination, _sync
from .decision_provenance import _state, _digest
from .db import utc_now

SCOPE = 'ai_quarter_review'
RELEASE = 'card.ai_review_corrected'
RESTORE = 'card.ai_review_restored'
FIELDS = ('item', 'description', 'display_tab_id', 'trip_id', 'classification_state',
          'classification_source', 'classification_basis')
MANUAL_SOURCES = {'user_decision', 'user_exception', 'owner_booking', 'manual', 'manual_hold'}
QUARTER_TAB = re.compile(r'quarter:(\d{4}):([1-4])')


def _validate(manifest):
    if not isinstance(manifest, dict):
        raise ValueError('MANIFEST_INVALID')
    review_id = manifest.get('review_id')
    reviewer = manifest.get('reviewer')
    corrections = manifest.get('corrections')
    if (not isinstance(review_id, str) or not review_id.strip()
            or not isinstance(reviewer, dict)
            or any(not isinstance(reviewer.get(k), str) or not reviewer[k].strip()
                   for k in ('provider', 'model', 'effort'))
            or not isinstance(corrections, list)):
        raise ValueError('MANIFEST_INVALID')
    seen = set()
    for correction in corrections:
        if (not isinstance(correction, dict)
                or any(not isinstance(correction.get(k), str)
                       for k in ('transaction_id', 'source_hash', 'display_tab_id', 'item', 'basis'))
                or not isinstance(correction.get('revision'), int)):
            raise ValueError('MANIFEST_INVALID')
        tid = correction['transaction_id']
        if tid in seen:
            raise ValueError('DUPLICATE_CORRECTION')
        seen.add(tid)
    return review_id, reviewer, corrections


def preview(conn, trips, manifest, *, evidence=None):
    from .automatic_classification import _read
    from .card_destination import observed_quarter
    from .partial_refund import refund_links
    from .review import correction_protection_reason
    review_id, reviewer, corrections = _validate(manifest)
    valid, manual = trip_map(trips), manual_ids(conn)
    rows = _read(conn)
    by_id = {r['transaction_id']: r for r in rows}
    linked = refund_links(conn, list(by_id))
    groups = _complete_refund_groups(conn, rows, linked)
    group_ids = set().union(*groups.values()) if groups else set()
    excluded = Counter()
    pending = {}
    for correction in corrections:
        tid = correction['transaction_id']
        row = by_id.get(tid)
        reason, group_candidate = '', False
        if (not row or row['source_hash'] != correction['source_hash']
                or row['revision'] != correction['revision']):
            reason = 'STALE'
        elif tid in manual or row.get('decided_at') or row['classification_source'] in MANUAL_SOURCES:
            reason = 'MANUAL_OR_USER_EXCEPTION'
        elif completed_period(row):
            reason = 'CLOSED_CARD_PERIOD'
        elif row.get('duplicate_of') or row.get('conflict_reason') or row.get('parse_error'):
            reason = 'SOURCE_PROTECTED'
        else:
            protection = correction_protection_reason(SimpleNamespace(conn=conn), tid, row['source_hash'])
            if protection.startswith('REVIEW_HOLD'):
                reason = 'REVIEW_HOLD'
            elif protection == 'COMPANY_EXCLUDED':
                reason = 'COMPANY_EXCLUDED'
            elif protection in {'CANCELLATION_OR_REFUND', 'ORIGINAL_WITH_REFUND'}:
                if tid in group_ids:
                    group_candidate = True
                    # The shared cancellation guard returns before hold/exclusion checks.
                    if conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=?', (tid,)).fetchone():
                        reason = 'REVIEW_HOLD'
                    elif conn.execute('SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=? AND excluded=1', (tid,)).fetchone():
                        reason = 'COMPANY_EXCLUDED'
                else:
                    reason = 'REFUND_UNPAIRED'
            elif protection:
                reason = 'SOURCE_PROTECTED'
        state = _state(conn, tid) if row else None
        from .trip_selection import past_trip
        if (not reason and correction['display_tab_id'] in valid
                and past_trip(row, valid[correction['display_tab_id']])):
            reason = 'PAST_TRIP'
        from .source_recheck import allowed as source_recheck_allowed
        source_fact = (evidence or {}).get(tid)
        source_exception = bool(not reason and source_recheck_allowed(
            conn, row, correction, manifest, source_fact, valid))
        legacy_owner = False
        if source_exception and source_fact.get('purpose') == 'manual_ledger_attribution':
            from .manual_ledger_recheck import legacy_owner_import
            legacy_owner = legacy_owner_import(conn, row)
        if not reason and manifest.get('scope') == 'q2_source_recheck' and not source_exception:
            reason = 'SOURCE_RECHECK_PROTECTED'
        if not reason:
            destinations = {row.get(k) for k in ('trip_id', 'display_tab_id')} - {None, '', 'unclassified'}
            if len(destinations) != 1:
                reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
            # Closed trips, closed quarters and unclassified rows are outside the
            # open-quarter review scope; nothing is pulled out of a closed period.
            elif not _open_destination(next(iter(destinations)), valid) and not source_exception:
                reason = 'CLOSED_CARD_PERIOD'
        if not reason:
            for projection in (state['ledger'], state['board']):
                if not projection or reason:
                    continue
                if projection.get('display_tab_id') not in destinations:
                    reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
                if projection is state['ledger'] and (projection.get('trip_id') or '') not in destinations | {''}:
                    reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
                if projection is state['board']:
                    payload = json.loads(projection['payload_json'])
                    if (any(k in payload and payload[k] not in destinations | ({''} if k == 'trip_id' else set())
                            for k in ('trip_id', 'display_tab_id'))
                            or (payload.get('confirmed_by') not in (None, '', 'automatic')
                                and not (legacy_owner and payload.get('confirmed_by') == 'owner'))):
                        reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
        tab = correction['display_tab_id']
        is_quarter = bool(QUARTER_TAB.fullmatch(tab))
        if not reason:
            if is_quarter:
                match = QUARTER_TAB.fullmatch(tab)
                quarter = observed_quarter(row)
                if (((int(match[1]), int(match[2])) < (2026, 3) and not source_exception)
                        or not quarter or quarter[0] != tab):
                    reason = 'INVALID_TARGET'
            elif not open_trip(valid.get(tab)):
                reason = 'INVALID_TARGET'
            if not reason and (not correction['item'].strip() or not correction['basis'].strip()):
                reason = 'INVALID_TARGET'
        if not reason:
            values = dict(item='분기 기타비용' if is_quarter else correction['item'],
                          description=row.get('description') or '',
                          display_tab_id=tab, trip_id='' if is_quarter else tab,
                          classification_state='classified', classification_source='ai_inference',
                          classification_basis='AI_REVIEW · ' + json.dumps(
                              dict(model=reviewer['model'], provider=reviewer['provider'],
                                   effort=reviewer['effort'], review_id=review_id),
                              ensure_ascii=False, sort_keys=True) + ' · ' + correction['basis'])
            if source_exception and source_fact.get('purpose') == 'manual_ledger_attribution':
                values['description'] = values['item'] + ' · 수기 원장 ' + source_fact['google_sheet']
            if all(row.get(k) == values[k] for k in FIELDS):
                reason = 'NO_CHANGE'
        if reason:
            excluded[reason] += 1
            continue
        before_tab = row['display_tab_id'] or row['trip_id']
        if before_tab == tab:
            kind = 'item_only'
        elif before_tab in valid:
            kind = 'trip_to_quarter' if is_quarter else 'trip_to_trip'
        else:
            kind = 'quarter_to_quarter' if is_quarter else 'quarter_to_trip'
        pending[tid] = dict(tid=tid, before=state, values=values, kind=kind,
                            group_candidate=group_candidate,
                            **({'source_recheck': source_fact} if source_exception else {}))
    moved_groups, refund_moved = 0, 0
    for original, members in groups.items():
        candidates = members & pending.keys()
        if not candidates:
            continue
        group_links = [linked[tid] for tid in members if tid in linked]
        reason = ''
        if not members <= pending.keys():
            reason = 'INELIGIBLE_MEMBER'
        elif len({pending[tid]['values']['display_tab_id'] for tid in members}) != 1:
            reason = 'DESTINATION_DISAGREEMENT'
        elif (not group_links or any(l.get('inferred') or l.get('status') not in ('full', 'partial')
                                     or l.get('net_krw', -1) < 0 for l in group_links)):
            reason = 'UNVERIFIED_OR_EXCESS'
        elif {l['original_id'] for l in group_links} != {original} or members != {original} | {tid for tid in members if tid in linked}:
            reason = 'INCOMPLETE_GROUP'
        if reason:
            for tid in candidates:
                pending.pop(tid)
            excluded['REFUND_' + reason] += len(candidates)
        else:
            # Every member already carries the same manifest destination.
            moved_groups += 1
            refund_moved += len(members)
    targets = [pending[k] for k in sorted(pending)]
    kinds, quarters = Counter(), Counter()
    for target in targets:
        kinds[target['kind']] += 1
        tab = target['values']['display_tab_id']
        if QUARTER_TAB.fullmatch(tab):
            quarters[tab] += 1
        before_tab = target['before']['transaction']['display_tab_id'] or ''
        if QUARTER_TAB.fullmatch(before_tab):
            quarters[before_tab] -= 1
    deltas = []
    for k, t in sorted(valid.items()):
        if not open_trip(t):
            continue
        moved = [x for x in targets if x['before']['transaction']['trip_id'] == k]
        added = [x for x in targets if x['values']['trip_id'] == k]
        deltas.append(dict(trip=t.get('display_key') or k, delta=len(added) - len(moved),
            ledger_delta=sum(bool(x['before']['ledger']) for x in added) - sum(bool(x['before']['ledger']) for x in moved),
            board_delta=sum(bool(x['before']['board']) for x in added) - sum(bool(x['before']['board']) for x in moved)))
    summary = dict(manifest_rows=len(corrections), to_apply=len(targets), kinds=dict(kinds),
                   excluded=dict(excluded), refund_move_rows=refund_moved, refund_move_groups=moved_groups,
                   open_trip_row_delta=deltas,
                   quarter_increases={k: v for k, v in sorted(quarters.items()) if v})
    return dict(digest=_digest([targets, trips, manifest, evidence or {}, _financial_state(conn)]),
                targets=targets, summary=summary)


def replay(conn, request_id):
    row = conn.execute('SELECT payload_sha256,response_json FROM requests WHERE request_id=? AND scope=?',
                       (request_id, SCOPE)).fetchone()
    return dict(digest=row[0], **json.loads(row[1])) if row else None


def apply(conn, expected, trips, manifest, *, request_id, evidence=None):
    if not request_id or conn.in_transaction:
        raise ValueError('AI_REVIEW_REQUEST_OR_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        prior = replay(conn, request_id)
        if prior:
            if expected['digest'] != prior['digest']:
                raise ValueError('AI_REVIEW_REQUEST_CONFLICT')
            conn.rollback()
            return dict(prior, replay=True, applied_this_run=0)
        current = preview(conn, trips, manifest, evidence=evidence)
        if expected['digest'] != current['digest']:
            raise ValueError('AI_REVIEW_PREVIEW_STALE')
        financial = _financial_state(conn)
        for target in current['targets']:
            tid, values = target['tid'], target['values']
            conn.execute('UPDATE transactions SET ' + ','.join(k + '=?' for k in FIELDS) +
                         ',revision=revision+1 WHERE transaction_id=?', (*[values[k] for k in FIELDS], tid))
            # _sync copies the whole values dict (source/state/basis included) into
            # the board payload; ledger_entries carries attribution fields only.
            _sync(conn, tid, values, request_id)
            detail = dict(request_id=request_id, before=target['before'], after=_state(conn, tid), financial=financial)
            if target.get('source_recheck'):
                detail['source_recheck'] = target['source_recheck']
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(), RELEASE, tid, json.dumps(detail, ensure_ascii=False, sort_keys=True)))
        if _financial_state(conn) != financial:
            raise ValueError('AI_REVIEW_FINANCIAL_CHANGED')
        result = dict(current['summary'], applied_this_run=len(current['targets']))
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
            raise ValueError('AI_REVIEW_RESTORE_STALE')
        if detail.get('financial', financial) != financial:
            raise ValueError('AI_REVIEW_RESTORE_FINANCIAL_STALE')
        targets.append(dict(entry=entry, tid=tid, detail=detail))
    return dict(digest=_digest([targets, financial]), targets=targets, summary=dict(restore=len(targets)))


def restore(conn, expected, request_id):
    if conn.in_transaction:
        raise ValueError('AI_REVIEW_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = restore_preview(conn, request_id)
        if current['digest'] != expected['digest']:
            raise ValueError('AI_REVIEW_PREVIEW_STALE')
        financial = _financial_state(conn)
        for target in current['targets']:
            tid, old = target['tid'], target['detail']['before']
            conn.execute('UPDATE transactions SET ' + ','.join(k + '=?' for k in FIELDS) +
                         ',revision=revision+1 WHERE transaction_id=?', (*[old['transaction'][k] for k in FIELDS], tid))
            _sync(conn, tid, old['ledger'] or old['transaction'], 'restore-' + request_id, old_board=old['board'])
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(), RESTORE, tid, json.dumps(dict(release_entry_id=target['entry'], request_id=request_id))))
        if _financial_state(conn) != financial:
            raise ValueError('AI_REVIEW_FINANCIAL_CHANGED')
        conn.commit()
        return current['summary']
    except BaseException:
        conn.rollback()
        raise
