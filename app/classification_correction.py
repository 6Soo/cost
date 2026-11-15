"""Revision-bound corrections of automatic classifications and existing projections.

No original, amount, financial link, decision or new ledger entry is written.
The audit records the actual automatic provenance and the previous values.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from .automatic_classification import FIELDS
from .db import utc_now
from .manual_overrides import exists_sql as manual_exists_sql
from .provisional_assignment import canonical_trip_periods
from .review import correction_protection_reason


def _open_p2_tab(trips, trip_id):
    if str(trip_id).startswith('quarter:'):
        try:
            value = str(trip_id).split(':', 1)[1]
            if ': ' in value:
                value = value.replace(': ', ':')
            if ':' in value:
                year, quarter = value.split(':', 1)
            else:
                year, quarter = value.split('-Q', 1)
            return (int(year), int(quarter)) >= (2026, 3)
        except (ValueError, TypeError):
            return False
    for trip in trips:
        if str(trip.get('trip_id') or trip.get('tab_id') or '') == str(trip_id):
            try:
                return trip.get('starts_on', '') >= '2026-06-30' and not trip.get('deleted') and not trip.get('archived')
            except (AttributeError, TypeError):
                return False
    return False


def _row(conn, table, column, identity):
    cursor = conn.execute(f'SELECT * FROM {table} WHERE {column}=?', (identity,))
    values = cursor.fetchone()
    return dict(zip((d[0] for d in cursor.description), values)) if values else None


def preview(conn, corrections, trips, *, allow_recorded_ai=False, completed_evidence=None):
    from .decision_provenance import active_decision_sql, closed_review_required
    valid = canonical_trip_periods(trips)
    targets = []
    seen = set()
    for correction in corrections:
        tid = correction['transaction_id']
        if tid in seen:
            raise ValueError('DUPLICATE_CORRECTION')
        seen.add(tid)
        row = _row(conn, 'transactions', 'transaction_id', tid)
        if not row or row['source_hash'] != correction['source_hash']:
            raise ValueError('CORRECTION_SOURCE_CHANGED')
        from .closed_period import excluded, completed_period, exception_trip
        proof = (completed_evidence or {}).get(tid)
        if excluded(row, trips, evidence=proof):
            raise ValueError('CORRECTION_PROTECTED')
        if completed_period(row) and correction['trip_id'] != exception_trip(row,trips,evidence=proof):
            raise ValueError('CORRECTION_INVALID_ATTRIBUTION')
        if 'revision' in correction and correction['revision'] != row['revision']:
            raise ValueError('CORRECTION_PREVIEW_STALE')
        source = correction.get('classification_source', 'inference')
        if allow_recorded_ai and source == 'ai_inference':
            allowed_keys = {'transaction_id', 'source_hash', 'revision', 'trip_id', 'item', 'basis',
                            'classification_source', 'execution', 'p2_metadata', 'description'}
            if set(correction) - allowed_keys:
                raise ValueError('CORRECTION_IMMUTABLE_FIELD')
        if source not in ('inference', 'code_inference', 'ai_inference'):
            raise ValueError('CORRECTION_SOURCE_INVALID')
        if source == 'ai_inference':
            execution = correction.get('execution') or {}
            if (execution.get('kind') != 'connected_agent'
                    or any(not isinstance(execution.get(k), str) or not execution[k].strip()
                           or len(execution[k]) > 160 for k in ('provider', 'model', 'run_id'))):
                raise ValueError('AI_EXECUTION_REQUIRED')
        if closed_review_required(conn,tid) or correction_protection_reason(SimpleNamespace(conn=conn),tid,row['source_hash']):
            raise ValueError('CORRECTION_PROTECTED')
        if (row['decided_at'] is not None
                or row['classification_source'] in {'user_decision','user_exception','owner_booking','manual'}
                or any(row.get(k) for k in ('parse_error','duplicate_of','conflict_reason'))
                or conn.execute('SELECT 1 FROM review_decisions d WHERE transaction_id=? AND '+active_decision_sql(), (tid,)).fetchone()
                or conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=?', (tid,)).fetchone()
                or conn.execute('SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=? AND excluded=1', (tid,)).fetchone()
                or conn.execute('SELECT ' + manual_exists_sql(conn, '?'), ('card-'+tid,)).fetchone()[0]):
            raise ValueError('CORRECTION_PROTECTED')
        if row['transaction_direction'] != 'purchase':
            raise ValueError('CORRECTION_REQUIRES_PURCHASE')
        trip = correction['trip_id']
        from .quarter_costs import _tab_of
        same_quarter = source == 'ai_inference' and trip == _tab_of(row)
        quarter = same_quarter and correction['item'] == '분기 기타비용'
        if allow_recorded_ai and correction['item'] != '분기 기타비용':
            quarter = same_quarter and _open_p2_tab(trips, trip)
        if (trip not in valid and not quarter) or not correction['item'] or not correction['basis']:
            raise ValueError('CORRECTION_INVALID_ATTRIBUTION')
        ledger = _row(conn, 'ledger_entries', 'transaction_id', tid)
        if ledger and source == 'ai_inference':
            same_trip = (trip == (row.get('display_tab_id') or row.get('trip_id')))
            if not (allow_recorded_ai and same_trip and _open_p2_tab(trips, trip)):
                raise ValueError('CORRECTION_PROTECTED')
        board = _row(conn, 'board_rows', 'row_id', 'card-'+tid)
        if board and board['row_kind'] != 'expense':
            raise ValueError('CORRECTION_PROJECTION_CONFLICT')
        targets.append(dict(before=row, ledger=ledger, board=board, correction=dict(correction)))
    inputs = [targets,trips]
    if completed_evidence:
        inputs.append({k:v for k,v in completed_evidence.items() if k in seen})
    payload = json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str)
    return dict(digest=hashlib.sha256(payload.encode()).hexdigest(), targets=targets,
                count=len(targets))


def apply(conn, expected, corrections, trips, *, request_id, allow_recorded_ai=False, completed_evidence=None):
    if not request_id:
        raise ValueError('CORRECTION_REQUEST_REQUIRED')
    payload_hash = hashlib.sha256(json.dumps(corrections,sort_keys=True).encode()).hexdigest()
    nested = conn.in_transaction
    conn.execute('SAVEPOINT attribution_correction' if nested else 'BEGIN IMMEDIATE')
    try:
        previous = conn.execute("SELECT payload_sha256,response_json FROM requests WHERE request_id=? AND scope='classification_correction'", (request_id,)).fetchone()
        if previous:
            if previous[0] != payload_hash:
                raise ValueError('CORRECTION_REQUEST_CONFLICT')
            result = dict(json.loads(previous[1]), applied=0, replay=True)
        else:
            current = preview(conn,corrections,trips,allow_recorded_ai=allow_recorded_ai,
                              completed_evidence=completed_evidence)
            if current['digest'] != expected['digest']:
                raise ValueError('CORRECTION_PREVIEW_STALE')
            for target in current['targets']:
                old, fix = target['before'], target['correction']
                tid, trip = old['transaction_id'], fix['trip_id']
                source = fix.get('classification_source', 'inference')
                basis = ('AI_INFERRED · ' + json.dumps(fix['execution'], ensure_ascii=False, sort_keys=True)
                         if source == 'ai_inference' else 'CODE_INFERRED')
                if fix.get('p2_metadata'):
                    basis += ' · P2_METADATA ' + json.dumps(fix['p2_metadata'], ensure_ascii=False, sort_keys=True)
                after = dict(classification_state='classified',classification_source=source,
                    classification_basis=basis+' · '+fix['basis'],item=fix['item'],
                    description=fix.get('description',old['description']) or '',display_tab_id=trip,trip_id=trip)
                if source == 'ai_inference' and trip.startswith('quarter:'):
                    after['trip_id'] = ''
                conn.execute('UPDATE transactions SET '+','.join(k+'=?' for k in FIELDS)+
                    ',revision=revision+1 WHERE transaction_id=? AND revision=?',
                    (*[after[k] for k in FIELDS],tid,old['revision']))
                if target['ledger']:
                    conn.execute('UPDATE ledger_entries SET item=?,description=?,display_tab_id=?,trip_id=? WHERE transaction_id=?',
                        (after['item'],after['description'],trip,trip,tid))
                if target['board']:
                    board = target['board']
                    payload = json.loads(board['payload_json'])
                    payload.update(item=after['item'],description=after['description'],display_tab_id=trip,
                                   classification_state='classified',classification_source=source,
                                   classification_basis=after['classification_basis'])
                    if 'revision' in payload:
                        payload['revision'] = board['revision'] + 1
                    if 'trip_id' in payload:
                        payload['trip_id'] = trip
                    conn.execute('UPDATE board_rows SET display_tab_id=?,payload_json=?,revision=revision+1 WHERE row_id=?',
                        (trip,json.dumps(payload,ensure_ascii=False,sort_keys=True),'card-'+tid))
                detail = dict(request_id=request_id,source_hash=old['source_hash'],
                    previous={k:old[k] for k in FIELDS},after=after,
                    previous_ledger=target['ledger'],previous_board=target['board'],
                    source='agent_evidence_review' if source == 'ai_inference' else 'code_inference',
                    execution=fix.get('execution'), user_booking_or_refund_confirmation=False)
                if fix.get('p2_metadata'):
                    detail['p2_metadata'] = fix['p2_metadata']
                conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                    (utc_now(),'card.classification_corrected',tid,json.dumps(detail,ensure_ascii=False,sort_keys=True)))
            result = dict(applied=current['count'],replay=False)
            conn.execute('INSERT INTO requests(request_id,scope,payload_sha256,response_json,created_at) VALUES (?,?,?,?,?)',
                (request_id,'classification_correction',payload_hash,json.dumps(result),utc_now()))
        conn.execute('RELEASE SAVEPOINT attribution_correction' if nested else 'COMMIT')
        return result
    except BaseException:
        if nested:
            conn.execute('ROLLBACK TO SAVEPOINT attribution_correction')
            conn.execute('RELEASE SAVEPOINT attribution_correction')
        else:
            conn.rollback()
        raise
