"""Read-only masked roster matching against a consistent Google income generation."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import sqlite3

from app.insurance_income_match import ManifestError, load_review_manifest, match_contract
from app.google_authority import SnapshotError


def _failure(code, message):
    return {'available': False, 'code': code, 'message': message, 'contracts': [], 'counts': {}}


def _current_trips():
    from . import ledger_board
    return [trip for trip in ledger_board.live_trips(include_archived=True)
            if trip.get('tab_id') not in ('unclassified', 'refunds')
            and not str(trip.get('tab_id', '')).startswith('quarter:')]


def _income_context(trips):
    from app import google_authority, participant_income
    from . import google_ledger_page as google
    if not google.enabled():
        raise ValueError('income unavailable')
    path = google.snapshot_path()
    snapshot, private = google_authority.load_consistent(path, google.rows_path())
    mapping = google.load_mapping(path)
    choices = google.load_choices(path)
    payload = google.owner_payload(google.snapshot_for_display(snapshot), choices)
    by_key = {trip['key']: trip for trip in payload['trips']}
    result, blocked = {}, set()
    for trip in trips:
        tid = trip['tab_id']
        keys = [key for key, value in mapping.items() if value == tid]
        if len(keys) != 1:
            blocked.add(tid)
            continue
        key = keys[0]
        chosen = by_key.get(key) or {}
        source = chosen.get('chosen_source')
        record = (payload.get('sources') or {}).get(source) or {}
        if source not in ('main', 'archive') or record.get('stale') or record.get('status') != 'ok':
            blocked.add(tid)
            continue
        detail = google.owner_rows(private, key, source)
        index = google.owner_income_names(private, key, source)
        if detail is None:
            blocked.add(tid)
            continue
        rows = participant_income.income_rows_from_trip(
            index=copy.deepcopy(index) if index and index.get('available') else {},
            amount_rows=detail.get('income', []), source=source, sheet=key)
        result[tid] = [dict(row, date=(row.get('cells') or {}).get('B') or '',
                            trip_id=tid, trip_name=trip.get('display_key') or tid) for row in rows]
    return {'rows_by_trip': result, 'blocked_trip_ids': blocked,
            'generation': snapshot.get('rows_generation'), 'mapping': mapping, 'choices': choices}


def _overlaps(contract, trip):
    try:
        start, end = dt.date.fromisoformat(contract['travel_start']), dt.date.fromisoformat(contract['travel_end'])
        a, b = dt.date.fromisoformat(trip['starts_on']), dt.date.fromisoformat(trip['ends_on'])
        return a <= end and start <= b
    except (KeyError, TypeError, ValueError):
        return False


def build_state(query=None, *, review=None, trips=None, context=None):
    """Project text associations only; never persist identities or financial links."""
    query = query or {}
    try:
        selected = query.get('trip', [''])[0]
        contract_filter = query.get('contract_key', [''])[0]
        if not isinstance(selected, str) or not isinstance(contract_filter, str) or len(selected) > 128 or len(contract_filter) > 64:
            return _failure('INVALID_FILTER', '조회 조건을 확인해 주세요.')
        if review is None:
            path = os.environ.get('WEBLEDGER_INSURANCE_REVIEW_MANIFEST')
            if not path:
                return _failure('REVIEW_NOT_CONFIGURED', '보험 명단 대조 자료가 연결되지 않았습니다.')
            review = load_review_manifest(path)
        trips = _current_trips() if trips is None else trips
        by_id = {trip['tab_id']: trip for trip in trips}
        if selected and selected not in by_id:
            return _failure('INVALID_FILTER', '기존 여행을 선택해 주세요.')
        if contract_filter and contract_filter not in {item['contract_key'] for item in review['contracts']}:
            return _failure('INVALID_FILTER', '기존 보험 명단을 선택해 주세요.')
        context = _income_context(trips) if context is None else context
    except (ManifestError, SnapshotError, OSError, ValueError, KeyError, TypeError, IndexError, sqlite3.Error):
        return _failure('MATCH_SOURCE_UNAVAILABLE', '보험 명단 또는 현재 수입 자료를 확인할 수 없습니다.')

    all_ids = set(by_id)
    options = [{'trip_id': tid, 'trip_name': trip.get('display_key') or tid} for tid, trip in by_id.items()]
    contracts = []
    totals = {key: 0 for key in ('contracts', 'rows', 'matched', 'ambiguous', 'unmatched', 'no_visible_letters', 'source_unavailable')}
    for contract in review['contracts']:
        if contract_filter and contract['contract_key'] != contract_filter:
            continue
        mapped = contract.get('cost_trip_id')
        periods = {tid for tid, trip in by_id.items() if _overlaps(contract, trip)}
        if selected:
            ids, scope = {selected}, '선택한 여행의 수입에서 대조'
        elif mapped:
            ids, scope = {mapped}, '명단에 연결된 여행의 수입에서 대조'
        elif periods:
            ids, scope = periods, '이용기간이 겹치는 기존 여행의 수입에서 대조'
        else:
            ids, scope = all_ids, '일정 후보가 없어 기존 전체 여행의 수입에서 글자 대조'
        blocked = not ids or bool(ids - all_ids) or bool(ids & set(context.get('blocked_trip_ids', ())))
        income_rows = [row for tid in sorted(ids) for row in context['rows_by_trip'].get(tid, [])] if not blocked else []
        matched = match_contract(contract, income_rows)
        if blocked:
            matched = {'rows': [dict(row, match_state='source_unavailable', matches=[], candidate_count=0)
                                for row in contract['rows']],
                       'counts': {'source_unavailable': len(contract['rows'])}}
            scope += ' · 수입 연결 또는 최신 자료 확인 필요'
        contracts.append({key: contract[key] for key in ('contract_key', 'travel_start', 'travel_end', 'insurance_status')}
                         | {'trip_options': options, 'scope_label': scope, **matched})
        totals['contracts'] += 1
        totals['rows'] += len(matched['rows'])
        for key, count in matched['counts'].items():
            totals[key] += count
    fingerprint = hashlib.sha256(json.dumps({
        'review': review['fingerprint'], 'generation': context.get('generation'),
        'mapping': context.get('mapping'), 'choices': context.get('choices'), 'trip': selected,
        'contract': contract_filter, 'trips': trips,
        'blocked': sorted(context.get('blocked_trip_ids', ())),
        'income': sorted((row['ref'], row['fingerprint']) for rows in context['rows_by_trip'].values() for row in rows),
    }, ensure_ascii=True, sort_keys=True).encode()).hexdigest()
    return {'available': True, 'code': 'PARTIAL' if totals['source_unavailable'] else 'OK',
            'message': '보이는 글자와 글자 수가 일치하는 기존 수입을 대조했습니다.',
            'fingerprint': fingerprint, 'contracts': contracts, 'counts': totals,
            'contract_options': [{'contract_key': item['contract_key'],
                                  'travel_start': item['travel_start'], 'travel_end': item['travel_end'],
                                  'row_count': len(item['rows'])} for item in review['contracts']]}
