"""Owner-only, read-only service for trip plus signed amount expense groups."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app import google_authority
from . import google_ledger_page, ledger_board, sheet_expense_reconciliation


def _amount(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('AMOUNT_UNCERTAIN')
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer() or abs(value) > 2**53:
            raise ValueError('AMOUNT_UNCERTAIN')
        return int(value)
    if not isinstance(value, str):
        raise ValueError('AMOUNT_UNCERTAIN')
    text = value.strip()
    if not re.fullmatch(r'[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)', text):
        raise ValueError('AMOUNT_UNCERTAIN')
    try:
        number = Decimal(text.replace(',', ''))
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError('AMOUNT_UNCERTAIN')
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError('AMOUNT_UNCERTAIN')
    return int(number)


def _state_unavailable(trip_id, reason, last_success_at=None):
    return {'available': False, 'reason': reason, 'last_success_at': last_success_at,
            'groups': [], 'by_cost_id': {},
            'summary': {'matched': 0, 'partial': 0, 'unrecorded': 0, 'google_only': 0,
                        'unavailable': 0}}


def build_state(board, trip_id, cost_rows=None):
    """Build amount-only group state after owner and source-authority checks.

    ``cost_rows``, when supplied, is the caller's whole-trip, refund-protected
    expense region. Each displayed board ``row_id`` stays distinct from its
    underlying ``source_event_id``.
    """
    if getattr(board, 'current_role', ledger_board.current_role)() != 'owner':
        return _state_unavailable(trip_id, 'OWNER_REQUIRED')
    if not trip_id or str(trip_id) == 'unclassified':
        return _state_unavailable(trip_id, 'COST_TRIP_UNAVAILABLE')
    try:
        store, cost_trip = sheet_expense_reconciliation._store_and_trip(board, str(trip_id))
        if store is None or cost_trip is None:
            raise ValueError('COST_TRIP_UNAVAILABLE')
        raw_costs = (list(cost_rows) if cost_rows is not None else
                     sheet_expense_reconciliation._cost_preview_rows(store, str(trip_id)))
        if not google_ledger_page.enabled():
            raise ValueError('GOOGLE_SOURCE_DISABLED')
        snapshot_path = google_ledger_page.snapshot_path()
        snapshot, all_rows = google_authority.load_consistent(
            snapshot_path, google_ledger_page.rows_path())
        snapshot = google_ledger_page.snapshot_for_display(snapshot)
        last_success_at = snapshot.get('synced_at')
        mapping = google_ledger_page.load_mapping(snapshot_path)
        keys = [key for key, mapped_trip in mapping.items()
                if str(mapped_trip) == str(trip_id)]
        if len(keys) != 1:
            raise ValueError('TRIP_MAPPING_UNAVAILABLE')
        google_key = keys[0]
        resolved = google_ledger_page.owner_payload(
            snapshot, google_ledger_page.load_choices(snapshot_path))
        trip_matches = [item for item in resolved.get('trips', [])
                        if item.get('key') == google_key]
        if len(trip_matches) != 1:
            raise ValueError('GOOGLE_TRIP_UNAVAILABLE')
        trip = trip_matches[0]
        source = trip.get('chosen_source')
        if source not in ('main', 'archive'):
            raise ValueError('SOURCE_NOT_SELECTED')
        source_info = (resolved.get('sources') or {}).get(source) or {}
        last_success_at = source_info.get('last_ok_at') or last_success_at
        copy_info = (trip.get('copies') or {}).get(source) or {}
        if (source_info.get('status') != 'ok' or source_info.get('stale')
                or copy_info.get('layout') != 'rev'
                or not (copy_info.get('expense') or {}).get('verified')
                or set(trip.get('review') or ()) & sheet_expense_reconciliation.BLOCKING_TRIP_FLAGS):
            raise ValueError('SOURCE_NOT_VERIFIED')
        sheet_id = copy_info.get('sheet')
        source_record = all_rows.get(source) or {}
        source_hash = source_record.get('content_sha256')
        snapshot_hash = (snapshot.get('sources', {}).get(source) or {}).get('content_sha256')
        if (not sheet_id or not isinstance(source_hash, str)
                or not re.fullmatch(r'[0-9a-f]{64}', source_hash)
                or source_hash != snapshot_hash):
            raise ValueError('SOURCE_FINGERPRINT_MISMATCH')
        detail = google_ledger_page.owner_rows(all_rows, google_key, source)
        if detail is None:
            raise ValueError('SHEET_ROWS_UNAVAILABLE')
        sheet_rows = sheet_expense_reconciliation._sheet_rows(
            detail['expense'], trip_id=trip_id, google_key=google_key,
            sheet_id=sheet_id, source=source)
        last_success_at = source_info.get('last_ok_at') or snapshot.get('synced_at')

        # Import the sibling pure core lazily so this service can be tested while
        # its separately owned implementation is being integrated.
        from app.expense_amount_groups import reconcile_expense_amount_groups
        costs = []
        for raw in raw_costs:
            row = dict(raw)
            row_id = str(row.get('row_id') or row.get('transaction_id') or row.get('source_event_id') or '')
            source_id = str(row.get('source_event_id') or row.get('transaction_id') or row_id)
            if not row_id or not source_id:
                raise ValueError('RECONCILIATION_INVALID')
            row_trip = str(row.get('display_tab_id') or row.get('trip_id') or '')
            if row_trip != str(trip_id):
                raise ValueError('COST_TRIP_UNAVAILABLE')
            amount = _amount(row.get('display_amount_krw', row.get('amount_krw')))
            currency = row.get('currency') or 'KRW'
            if str(currency).upper() != 'KRW':
                raise ValueError('AMOUNT_UNCERTAIN')
            costs.append({'row_id': row_id, 'source_identity': source_id,
                          'trip_id': str(trip_id), 'amount_krw': amount, 'currency': 'KRW',
                          'date': row.get('display_occurred_on') or row.get('occurred_on') or '',
                          'description': row.get('description') or '',
                          'payee': row.get('source_merchant') or row.get('description') or ''})
        google = []
        for row in sheet_rows:
            amount = _amount(row.get('amount_krw'))
            currency = row.get('currency') or 'KRW'
            if str(currency).upper() != 'KRW' or not row.get('sheet_row_key'):
                raise ValueError('AMOUNT_UNCERTAIN')
            google.append({'ref': str(row.get('sheet_row_key')),
                           'row_number': row.get('row_number'),
                           'trip_id': str(trip_id), 'amount_krw': amount, 'currency': 'KRW',
                           'date': row.get('date') or '',
                           'description': row.get('description') or row.get('category') or '',
                           'payee': row.get('payee') or ''})
        state = reconcile_expense_amount_groups(str(trip_id), costs, google,
                                                available=True,
                                                last_success_at=last_success_at)
        if not isinstance(state, dict) or not isinstance(state.get('groups'), list):
            raise ValueError('RECONCILIATION_INVALID')
        if state.get('available') is not True:
            raise ValueError(state.get('reason') or 'RECONCILIATION_INVALID')
        if any(str(group.get('trip_id')) != str(trip_id) for group in state['groups']):
            raise ValueError('RECONCILIATION_INVALID')
        by_cost = state.get('by_cost_id')
        expected_ids = {row['row_id'] for row in costs}
        if not isinstance(by_cost, dict) or not expected_ids.issubset(by_cost):
            raise ValueError('RECONCILIATION_INVALID')
        if not set(by_cost).issubset(expected_ids):
            raise ValueError('RECONCILIATION_INVALID')
        return state
    except Exception as error:
        codes = {'AMOUNT_UNCERTAIN', 'COST_TRIP_UNAVAILABLE', 'GOOGLE_SOURCE_DISABLED',
                 'TRIP_MAPPING_UNAVAILABLE', 'GOOGLE_TRIP_UNAVAILABLE', 'SOURCE_NOT_SELECTED',
                 'SOURCE_NOT_VERIFIED', 'SOURCE_FINGERPRINT_MISMATCH', 'SHEET_ROWS_UNAVAILABLE',
                 'RECONCILIATION_INVALID', 'INVALID_OR_UNCERTAIN_ROW'}
        reason = str(error) if isinstance(error, ValueError) and str(error) in codes else 'SOURCE_UNAVAILABLE'
        return _state_unavailable(trip_id, reason, locals().get('last_success_at'))


def sort_for_display(rows, state):
    """Stable display-only order: exact groups, partial groups, then no match.

    Within each matching tier use the first actual Google sheet row. M:N
    groups share that position; input order breaks ties without inventing pairs.
    """
    if not state or state.get('available') is not True:
        return list(rows)
    positions = {}
    for group in state.get('groups') or []:
        numbers = [r['row_number'] for r in group.get('google_rows') or []
                   if type(r.get('row_number')) is int and r['row_number'] > 0]
        positions[group['group_id']] = min(numbers) if numbers else float('inf')
    annotations = state.get('by_cost_id') or {}
    def key(row):
        annotation = annotations.get(row.get('row_id')) or {}
        tier = {'matched': 0, 'partial': 1}.get(annotation.get('status'), 2)
        return tier, positions.get(annotation.get('group_id'), float('inf')) if tier < 2 else float('inf')
    return sorted(rows, key=key)
