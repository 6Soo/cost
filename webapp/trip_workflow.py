"""Owner-only review links projected from existing sources, never saved state."""
from __future__ import annotations

import html
from urllib.parse import urlencode

from . import expense_amount_group_service as groups, google_ledger_page as google, receipt_review, ui_icons


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
    links = [('users', '보험 후보 비교', '수입 표의 후보 버튼을 눌러 가림 이름·기간을 비교하세요.', '#participant-trip-panel'),
             ('table', '지출 검토·복사', '지출표에서 장부 기록 여부를 확인하고 새 지출을 복사하세요.', '#trip-expense-copy'),
             ('archive', '수입·마감 확인', closure + ' · 수입 합계와 장부 위치를 확인하세요.', '#trip-income'),
             ('credit-card', '카드 원천', '전체 여행의 카드 원본 보기', '/cards/all'),
             ('list-filter', '미정리·보류', f"이 여행 표시 지출 보류 {state['displayed_holds']}건 · 전체 미정리 화면 열기", '/import'),
             ('link', 'OTA·환불', '결제·환불 근거 확인', '/ota'),
             ('receipt', '영수증', receipt_text + ' · 전체 영수증 화면 열기', '/receipts')]
    cards = [
        f"<a class='trip-workflow-card' href='{esc(href)}'>"
        f"<span class='trip-workflow-icon'>{ui_icons.icon(icon, 18)}</span>"
        f"<span class='trip-workflow-copy'><strong>{esc(label)}</strong>"
        f"<span>{esc(text)}</span></span>"
        f"<span class='trip-workflow-arrow'>{ui_icons.icon('chevron-right', 16)}</span></a>"
        for icon, label, text, href in links]
    return ("<details class='trip-workflow' aria-label='여행 검토' open><summary>"
            f"<span class='trip-workflow-heading'>{ui_icons.icon('list-filter', 18)}여행 검토</span>"
            f"<span class='trip-workflow-toggle'>{ui_icons.icon('chevron-down', 16)}</span></summary>"
            "<nav class='trip-workflow-grid' aria-label='이 여행 검토 작업'>" + ''.join(cards[:3]) + '</nav>'
            "<details class='trip-workflow-tools'><summary>전체 자료·도구 열기</summary>"
            "<nav class='trip-workflow-grid' aria-label='전체 자료 도구'>" + ''.join(cards[3:]) + '</nav></details></details>')
