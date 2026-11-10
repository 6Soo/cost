"""Owner-only review links projected from existing sources, never saved state."""
from __future__ import annotations

from urllib.parse import urlencode

from . import expense_amount_group_service as groups, google_ledger_page as google, receipt_review
from .ui_components import steps


def _receipts(trip_id):
    if not receipt_review.enabled():
        return {'available': False, 'reason': 'DISABLED'}
    try:
        path = receipt_review._store_path()
        if not path.is_file():
            return {'available': False, 'reason': 'STORE_UNAVAILABLE'}
        data = receipt_review.load(path)
        selected = [c for c in data['candidates'] if c.get('trip_id') == trip_id]
        return {'available': True, 'count': len(selected),
                'held': sum(bool(c.get('hold')) for c in selected)}
    except (OSError, ValueError):
        return {'available': False, 'reason': 'STORE_UNAVAILABLE'}


def build_state(board, trip_id, cost_rows, amount_groups):
    """Closure, displayed holds and receipts are independent of M:N equality."""
    from . import ledger_board
    from app.quarter_tab import parse_tab
    if getattr(board, 'current_role', ledger_board.current_role)() != 'owner':
        return None
    if trip_id in ('unclassified', 'refunds') or not trip_id or parse_tab(trip_id) or trip_id.startswith('quarter:'):
        return None
    state = {'closure': 'unknown', 'duplicate_copy': False,
             'google_available': bool(amount_groups and amount_groups.get('available')),
             'last_success_at': (amount_groups or {}).get('last_success_at'),
             'displayed_holds': sum(bool(r.get('blocked')) for r in cost_rows),
             'receipts': _receipts(trip_id), 'trip_id': trip_id}
    try:
        if not google.enabled():
            return state
        _, _, mapping, payload = groups._source_bundle()
        keys = [key for key, tid in mapping.items() if tid == trip_id]
        trips = [trip for trip in payload.get('trips', []) if trip.get('key') in keys]
        if len(keys) != 1 or len(trips) != 1:
            return state
        trip = trips[0]
        sources = payload.get('sources') or {}
        current = all((sources.get(role) or {}).get('status') == 'ok'
                      and not sources[role].get('stale') for role in ('main', 'archive'))
        identity_clear = not (set(trip.get('review') or []) & google.OWNER_CHOICE_BLOCKERS)
        if current and identity_clear and trip.get('closure_current'):
            if trip.get('closure') == 'closed' and (trip.get('copies') or {}).get('archive'):
                state['closure'] = 'closed'
            elif trip.get('closure') == 'open':
                state['closure'] = 'open'
        state['duplicate_copy'] = 'DUPLICATE_IN_BOTH' in (trip.get('review') or [])
    except Exception:
        pass
    return state


def render(board, trip_id, cost_rows, amount_groups):
    state = build_state(board, trip_id, cost_rows, amount_groups)
    if state is None:
        return ''

    # PR-4 replaces the old equal-weight review cards with one ordered list.  The
    # values below are projections of the existing state only; no new aggregation
    # or user task is created here.
    missing_service_dates = 0
    try:
        from . import ledger_design
        for row in cost_rows or ():
            if row.get('row_kind') != 'expense':
                continue
            compact, _title = ledger_design._service_date_labels(row)
            if not compact or '미확인' in compact or '확인 필요' in compact:
                missing_service_dates += 1
    except Exception:
        missing_service_dates = sum(
            1 for row in cost_rows or ()
            if row.get('row_kind') == 'expense' and not row.get('service_period'))

    expense_note = f"{len(cost_rows or [])}건"
    if missing_service_dates:
        expense_note += f" · 이용일 원문 없음 {missing_service_dates}건"
    receipt = state.get('receipts') or {}
    receipt_note = (f"{receipt.get('count', 0)}건" if receipt.get('available')
                    else '자료를 읽지 못했습니다')
    domestic = False
    try:
        from .trip_insurance_policy import domestic_trip
        domestic = domestic_trip(trip_id)
    except Exception:
        pass
    income_note = '수입 확인' if domestic else '보험 후보 비교'
    summary = (amount_groups or {}).get('summary') or {}
    if state.get('google_available'):
        google_note = (f"미기록 {summary.get('unrecorded', 0)}그룹 · "
                       f"부분 일치 {summary.get('partial', 0)}그룹")
        google_done = not summary.get('unrecorded', 0) and not summary.get('partial', 0)
    else:
        google_note = '비교 불가'
        google_done = False
    closure_label = {'closed': '마감', 'open': '미마감', 'unknown': '확인 중'}.get(
        state.get('closure'), '확인 중')
    items = [
        {'label': '지출', 'note': expense_note, 'href': '#view-expense', 'state': 'todo'},
        {'label': '영수증', 'note': receipt_note,
         'href': '/receipts?' + urlencode({'trip': trip_id}), 'state': 'todo'},
        {'label': '수입·참가자', 'note': income_note, 'href': '#view-income', 'state': 'todo'},
        {'label': 'Google 복사', 'note': google_note,
         'href': '#copy-trip-expenses', 'state': 'done' if google_done else 'todo'},
        {'label': closure_label, 'note': '', 'href': '#trip-close',
         'state': 'done' if state.get('closure') == 'closed' else 'todo'},
    ]
    return (f"<section class='settlement-steps' id='trip-steps' aria-label='정산 단계'>"
            f"{steps(items)}</section>")
