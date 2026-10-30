"""Owner-only review links projected from existing sources, never saved state."""
from __future__ import annotations

import html
from urllib.parse import urlencode

from . import expense_amount_group_service as groups, google_ledger_page as google, receipt_review


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
    esc = lambda value: html.escape(str(value), quote=True)
    closure = {'closed':'보관 장부 이동 확인', 'open':'메인 장부 · 미마감', 'unknown':'마감 확인 필요'}[state['closure']]
    if state['duplicate_copy']:
        closure += ' · 사본 중복 검토'
    receipt = state['receipts']
    receipt_text = (f"{receipt['count']}건 · 보류 {receipt['held']}건" if receipt['available']
                    else '영수증 자료 확인 필요')
    google_text = '정본 대조 조회 가능' if state['google_available'] else '정본 대조 확인 필요'
    last_success = google.format_display_time(state['last_success_at'])
    match_url = '/participants/insurance-match?' + urlencode({'trip':trip_id})
    from .sheet_expense_review import PAGE_PATH
    google_url = PAGE_PATH + '?' + urlencode({'trip':trip_id})
    links = [('카드 원천', '수집 범위 확인', '/cards/all'),
             ('미정리·보류', f"표시 지출 보류 {state['displayed_holds']}건 · 전체 미정리 확인", '/import'),
             ('OTA·환불', '기존 대사에서 결제·환불 근거 확인', '/ota'),
             ('영수증', receipt_text, '/receipts'),
             ('Google 반영', google_text + ' · 마지막 정상 조회 ' + last_success, google_url),
             ('여행 마감', closure, '#trip-income'),
             ('보험 명단', '명단과 수입 글자 대조', match_url)]
    return ("<details class='trip-workflow' aria-label='여행 검토'><summary>여행 검토</summary>"
            "<dl>" + ''.join(f"<dt>{esc(label)}</dt><dd><a href='{esc(href)}'>{esc(text)}</a></dd>"
                             for label, text, href in links) + '</dl></details>')
