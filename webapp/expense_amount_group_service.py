"""Owner-only, read-only service for trip plus signed amount expense groups."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from . import ledger_board, sheet_expense_reconciliation


def _amount(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('AMOUNT_UNCERTAIN')
    try:
        number = Decimal(str(value).replace(',', '').strip())
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
    preview = sheet_expense_reconciliation.preview_for_trip(board, str(trip_id), cost_rows=[])
    if not preview.get('source_available'):
        return _state_unavailable(trip_id,
                                  (preview.get('source_info') or {}).get('reason', 'SOURCE_UNAVAILABLE'),
                                  ((preview.get('revision') or {}).get('synced_at')))
    try:
        # Import the sibling pure core lazily so this service can be tested while
        # its separately owned implementation is being integrated.
        from app.expense_amount_groups import reconcile_expense_amount_groups
        costs = []
        source_ids = set()
        for raw in (cost_rows if cost_rows is not None else preview.get('cost_rows') or ()):
            row = dict(raw)
            row_id = str(row.get('row_id') or '')
            source_id = str(row.get('source_event_id') or row.get('transaction_id') or row_id)
            if not row_id or not source_id:
                raise ValueError('RECONCILIATION_INVALID')
            row_trip = str(row.get('display_tab_id') or row.get('trip_id') or '')
            if row_trip != str(trip_id):
                raise ValueError('COST_TRIP_UNAVAILABLE')
            if source_id in source_ids:
                # The supplied region has already applied same-source and
                # refund protections. A duplicate source here is ambiguous.
                raise ValueError('RECONCILIATION_INVALID')
            source_ids.add(source_id)
            amount = _amount(row.get('display_amount_krw', row.get('amount_krw')))
            currency = row.get('currency') or 'KRW'
            if str(currency).upper() != 'KRW':
                raise ValueError('AMOUNT_UNCERTAIN')
            costs.append({'row_id': row_id, 'source_identity': source_id,
                          'trip_id': str(trip_id), 'amount_krw': amount, 'currency': 'KRW'})
        google = []
        for row in preview.get('sheet_rows') or ():
            amount = _amount(row.get('amount_krw'))
            currency = row.get('currency') or 'KRW'
            if str(currency).upper() != 'KRW' or not row.get('sheet_row_key'):
                raise ValueError('AMOUNT_UNCERTAIN')
            google.append({'ref': str(row.get('sheet_row_key')),
                           'trip_id': str(trip_id), 'amount_krw': amount, 'currency': 'KRW'})
        state = reconcile_expense_amount_groups(str(trip_id), costs, google,
                                                available=True,
                                                last_success_at=(preview.get('revision') or {}).get('synced_at'))
        if not isinstance(state, dict) or not isinstance(state.get('groups'), list):
            raise ValueError('RECONCILIATION_INVALID')
        # The function is trip-scoped. Discard malformed or cross-trip core output.
        if any(str(group.get('trip_id')) != str(trip_id) for group in state['groups']):
            raise ValueError('RECONCILIATION_INVALID')
        known_ids = {row['row_id'] for row in costs}
        if not isinstance(state.get('by_cost_id'), dict) or set(state['by_cost_id']) != known_ids:
            raise ValueError('RECONCILIATION_INVALID')
        return state
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) else 'SOURCE_UNAVAILABLE'
        return _state_unavailable(trip_id, reason,
                                  (preview.get('revision') or {}).get('synced_at'))
