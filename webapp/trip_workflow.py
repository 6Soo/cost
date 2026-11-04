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
    receipt_text = (f"이 여행 {receipt['count']}건 · 보류 {receipt['held']}건. 영수증의 금액·여행·결제수단을 확인하세요."
                    if receipt['available'] else '자료를 읽지 못해 건수를 확인할 수 없습니다. 영수증 화면에서 확인하세요.')
    summary = (amount_groups or {}).get('summary') or {}
    copy_text = (f"미기록 {summary.get('unrecorded', 0)}그룹 · 부분 일치 {summary.get('partial', 0)}그룹. "
                 '장부 표시를 대조한 뒤 복사 가능한 지출을 확인하세요.' if state['google_available']
                 else 'Google 장부와 비교할 수 없습니다. 비교 자료를 확인한 뒤 복사 여부를 판단하세요.')
    links = [('users', '보험 후보 비교', '수입의 보험 등록 후보를 비교하고, 맞는 참가자를 연결하거나 기존 연결을 교정하세요.', '#participant-trip-panel'),
             ('table', '지출 검토·복사', copy_text, '#trip-expense-copy'),
             ('receipt', '영수증 확인', receipt_text, '/receipts?' + urlencode({'trip': trip_id})),
             ('archive', '수입·마감 확인', closure + ' · 수입 내역과 출처를 확인하세요. 마감과 지출 기록은 별개입니다.', '#trip-income')]
    from .trip_insurance_policy import domestic_trip
    domestic = domestic_trip(trip_id)
    if domestic:
        links = links[1:]
    cards = [
        f"<a class='trip-workflow-card' href='{esc(href)}'"
        + (" data-trip-panel='participant-trip-panel'" if href == '#participant-trip-panel' else '') + ">"
        f"<span class='trip-workflow-icon'>{ui_icons.icon(icon, 18)}</span>"
        f"<span class='trip-workflow-copy'><strong>{esc(label)}</strong>"
        f"<span>{esc(text)}</span></span>"
        f"<span class='trip-workflow-arrow'>{ui_icons.icon('chevron-right', 16)}</span></a>"
        for icon, label, text, href in links]
    held = [row for row in cost_rows if row.get('blocked')]
    held_links = ''.join(
        f"<li><a href='/board?{esc(urlencode({'tab': trip_id, 'row': row['row_id']}))}'>"
        f"{esc(row.get('source_merchant') or row.get('description') or row.get('item') or '지출')} · 상세에서 보류 근거 확인</a></li>"
        for row in held if row.get('row_id'))
    holds = (f"<section class='trip-review-holds' aria-label='이 여행 보류 지출'><h3>보류 지출 {len(held)}건</h3>"
             + (f"<p>각 거래의 근거를 확인하고 필요한 항목을 교정하세요.</p><ul>{held_links}</ul>" if held
                else '<p>이 여행 지출에 보류 표시가 없습니다.</p>') + '</section>')
    return ("<details class='trip-workflow' id='trip-review-panel' aria-label='여행 검토'><summary>"
            f"<span class='trip-workflow-heading'>{ui_icons.icon('list-filter', 18)}여행 검토</span>"
            f"<span class='trip-workflow-toggle'>{ui_icons.icon('chevron-down', 16)}</span></summary>"
            "<nav class='trip-workflow-grid' aria-label='이 여행 검토 작업'>" + ''.join(cards) + '</nav>' + holds
            + "<details class='trip-workflow-tools'><summary>전체 여행 자료에서 더 찾기</summary>"
            "<p>아래 화면은 전체 여행 자료를 엽니다. 현재 여행으로 자동 필터되지 않습니다.</p>"
            "<nav class='trip-review-sources' aria-label='전체 자료 도구'>"
            "<a href='/cards/all'>카드 원본 찾기</a><a href='/ota'>OTA·환불 근거 찾기</a>"
            "<a href='/google-ledger'>Google 장부 사본·마감 관리</a></nav></details></details>")
