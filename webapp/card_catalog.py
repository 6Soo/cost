"""Owner-only, read-only listing of stored card transactions across all imports."""
import html
import re
from urllib.parse import urlencode

from app.db import decided_sql

from . import ui_icons

PAGE_SIZE = 50
STATES = {'needs_review': '확인 필요', 'booked': '기록 완료',
          'preserved': '기존 보존'}
TRADE_DATE = "COALESCE(NULLIF(t.approval_date,''),t.posting_date)"

from .card_catalog_assets import CATALOG_SCRIPT, CATALOG_STYLE



def catalog(board, query):
    value = lambda key: str((query.get(key) or [''])[0]).strip()
    q, card, state = value('q'), value('card'), value('state')
    month = value('month')
    if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', month):
        month = ''
    order = 'DESC' if value('sort') == 'desc' else 'ASC'
    try:
        page = max(1, int(value('page') or 1))
    except ValueError:
        page = 1
    columns = ('transaction_id', 'batch_id', 'approval_date', 'posting_date', 'issuer', 'card_tail',
               'transaction_direction', 'transaction_kind', 'merchant', 'amount_krw', 'foreign_amount',
               'foreign_currency', 'item', 'description', 'classification_state', 'decided',
               'duplicate_of', 'conflict_reason', 'parse_error', 'display_tab_id', 'classification_source')
    from .history_policy import cutoff
    boundary = cutoff()
    base = f"({TRADE_DATE} IS NULL OR {TRADE_DATE}='' OR {TRADE_DATE}>=?)" if boundary else ''
    where, params = ([base], [boundary]) if base else ([], [])
    if q:
        where.append("(instr(lower(t.merchant || ' ' || t.item || ' ' || t.description || ' ' || "
                     "t.approval_number || ' ' || COALESCE(p.display_key,'')),lower(?))>0)")
        params.append(q)
    if card:
        where.append('t.card_tail=?')
        params.append(card)
    if state:
        if state == 'booked':
            where.append('EXISTS (SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)')
        else:
            where.append('t.classification_state=?')
            params.append(state)
    if month:
        where.append(f"strftime('%Y-%m',{TRADE_DATE})=?")
        params.append(month)
    clause = ' WHERE ' + ' AND '.join(where) if where else ''
    source = (' FROM transactions t LEFT JOIN trip_tabs p ON p.tab_id=t.display_tab_id'
              ' LEFT JOIN transaction_company_exclusions e ON e.transaction_id=t.transaction_id')
    with board._lock:
        if not board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transactions'").fetchone():
            return {'rows': [], 'total': 0, 'all_count': 0, 'cards': [], 'months': [], 'page': 1, 'pages': 1}
        all_count = board.conn.execute('SELECT COUNT(*) FROM transactions t' +
            (' WHERE ' + base if base else ''), [boundary] if base else []).fetchone()[0]
        total = board.conn.execute('SELECT COUNT(*)' + source + clause, params).fetchone()[0]
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        records = board.conn.execute('SELECT ' + ','.join(decided_sql('t') if c == 'decided' else 't.' + c for c in columns)
            + ',COALESCE(p.display_key,\'\'),COALESCE(e.excluded,0)' + source + clause
            + f" ORDER BY ({TRADE_DATE} IS NULL OR {TRADE_DATE}=''),{TRADE_DATE} {order},t.transaction_id"
            + ' LIMIT ? OFFSET ?', [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        cards = [r[0] for r in board.conn.execute('SELECT DISTINCT card_tail FROM transactions t' +
            (' WHERE ' + base if base else '') + ' ORDER BY card_tail', [boundary] if base else [])]
        months = [r[0] for r in board.conn.execute(
            f"SELECT DISTINCT strftime('%Y-%m',{TRADE_DATE}) AS month FROM transactions t "
            'WHERE month IS NOT NULL' + (' AND ' + base if base else '') + ' ORDER BY month ASC',
            [boundary] if base else [])]
    rows = [dict(zip((*columns, 'trip_name', 'company_excluded'), row)) for row in records]
    from .refund_tab import groups
    complete = {r['transaction_id'] for group in groups(board) for r in group}
    for row in rows:
        if row['transaction_id'] in complete:
            row['trip_name'] = '환불'
    from app.review_holds import active_holds
    from .card_actions import next_action
    holds = active_holds(board.conn)
    booked = {r[0] for r in board.conn.execute('SELECT transaction_id FROM ledger_entries')}
    for row in rows:
        row['review_hold'] = holds.get(row['transaction_id'])
        row['next_action'] = next_action(row, {'already_booked': row['transaction_id'] in booked})
    if any(re.search(r'toyoko|토요코인', row.get('merchant') or '', re.I) for row in rows):
        from .card_flow import CardFlow
        notes = CardFlow(board)._ota_candidate_notes(rows)
        for row in rows:
            row['ota_candidate_notes'] = notes.get(row['transaction_id'], [])
    return {'rows': rows,
            'total': total, 'all_count': all_count, 'cards': cards, 'months': months, 'page': page, 'pages': pages}


def render_html(data, query, *, csrf=''):
    esc = lambda value: html.escape('' if value is None else str(value), quote=True)
    value = lambda key: str((query.get(key) or [''])[0])
    def link(page):
        return '/import?' + urlencode({**{k: value(k) for k in ('q', 'card', 'state', 'month', 'sort')},
                                       'scope': 'all', 'page': page})
    def choices(name, label, options, selected):
        return f'<h2>{esc(label)}</h2>' + ''.join(
            f"<button type='button' class='filter-option' data-filter='{name}' data-value='{esc(k)}' "
            f"aria-pressed='{'true' if k == selected else 'false'}'>{esc(text)}</button>" for k, text in options)
    def heading(key, label, selected, contents, icon_name):
        return (f"<th class='has-filter' scope='col'><button type='button' class='header-button' "
                f"aria-label='{label}' popovertarget='filter-{key}' aria-expanded='false' aria-controls='filter-{key}'>"
                f"{ui_icons.icon(icon_name, 14)}{label}<span class='header-value' aria-hidden='true'>{esc(selected)}</span>"
                f"{ui_icons.icon('chevron-down', 14)}</button>"
                f"<div id='filter-{key}' class='header-menu' popover aria-label='{label} 정렬 및 필터'>{contents}</div></th>")
    sort = 'desc' if value('sort') == 'desc' else 'asc'
    date_controls = choices('sort', '거래일 정렬', [('desc', '내림차순 · 최신 거래 먼저'), ('asc', '오름차순 · 오래된 거래 먼저')], sort)
    date_controls += choices('month', '조회 월', [('', '전체 월')]
                             + [(m, m.replace('-', '년 ') + '월') for m in data.get('months', [])], value('month'))
    date_heading = heading('date', '거래일', ('오름차순' if sort == 'asc' else '내림차순')
                           + (' · ' + value('month') if value('month') else ''), date_controls, 'calendar-days')
    card_heading = heading('card', '카드', value('card'), choices('card', '카드 선택',
                           [('', '모든 카드')] + [(c, c) for c in data['cards'] if c], value('card')), 'credit-card')
    state_heading = heading('state', '상태', STATES.get(value('state'), ''),
                            choices('state', '분류 상태', [('', '모든 상태'), *STATES.items()], value('state')), 'list-filter')
    hidden_filters = ''.join(f"<input type='hidden' name='{name}' value='{esc(value(name))}'>"
                             for name in ('sort', 'month', 'card', 'state'))
    rows = []
    for r in data['rows']:
        from app import quarter_costs
        quarter = quarter_costs.destination(r)
        from .card_actions import next_action
        action = r.get('next_action') or next_action(r)
        from .card_actions import GROUP_LABELS
        state = GROUP_LABELS.get(action.get('group'), '')
        if r['decided']:
            state += (' · ' if state else '') + '직접 분류'
        if r['duplicate_of']:
            state += (' · ' if state else '') + '중복'
        if r['company_excluded']:
            state += (' · ' if state else '') + '회사 경비 제외'
        if r['conflict_reason'] or r['parse_error']:
            state += (' · ' if state else '') + '오류 확인'
        direction = {'purchase': '결제', 'cancellation': '취소', 'refund': '환불'}.get(
            r['transaction_direction'], r['transaction_direction'])
        amount = f"{r['amount_krw']:,}원" if type(r['amount_krw']) is int else '금액 미확인'
        cells = [('거래일', r['approval_date'] or r['posting_date']),
                 ('카드', r['issuer'] + ' · ' + r['card_tail']), ('지급처', r['merchant']),
                 ('구분', direction + ' · ' + r['transaction_kind']), ('원본 금액', amount),
                 ('분류', r['item'] or '미분류'), ('여행', r['trip_name'] or
                  (quarter['name'] + ' · 여행 외 비용' if quarter else '여행 확인 필요')), ('상태', state)]
        row = ''.join(f"<td data-label='{esc(label)}'>{esc(text)}</td>" for label, text in cells)
        evidence = ''.join(f"<p class='small'>{esc(note)}</p>" for note in r.get('ota_candidate_notes') or ())
        rows.append(f"<tr data-transaction='{esc(r['transaction_id'])}'>" + row +
                    f"<td data-label='다음 행동'><p class='action-reason'>{esc(action['reason'])}</p>"
                    f"{evidence}<a class='catalog-btn' href='{esc(action['href'])}'>{esc(action['label'])}</a></td></tr>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><title>전체 카드 거래 검색</title>"
        f"<style>{CATALOG_STYLE}</style></head><body><main class='card-catalog'>"
        "<nav class='catalog-actions' aria-label='전체 카드 거래 탐색'>"
        f"<a class='catalog-btn' href='/import'>{ui_icons.icon('list')}정리할 지출 보기</a></nav>"
        "<h1>전체 카드 거래 검색</h1>"
        "<p class='small'>저장된 모든 카드 거래를 찾아봅니다. 처리는 거래를 눌러 지출 정리에서 합니다.</p>"
        f"<p id='card-count'>전체 {data['all_count']:,}건 · 검색 결과 {data['total']:,}건</p>"
        ""
        "<form id='card-filters' method='get' action='/import'><input name='q' aria-label='카드 거래 검색' placeholder='지급처·분류·설명·승인번호·여행 검색'"
        f" value='{esc(value('q'))}'><button class='catalog-btn primary' type='submit'>{ui_icons.icon('search')}검색</button>"
        f"<a class='catalog-btn' href='/import?scope=all'>{ui_icons.icon('rotate-ccw')}초기화</a>"
        + hidden_filters + "<input type='hidden' name='scope' value='all'></form>"
        + "<table><thead><tr>" + date_heading + card_heading
        + ''.join(f"<th scope='col'>{s}</th>" for s in ('지급처', '구분', '원본 금액', '분류', '여행'))
        + state_heading + "<th scope='col'>다음 행동</th>"
        + '</tr></thead><tbody>' + (''.join(rows) or '<tr><td colspan="9">조건에 맞는 카드 내역이 없습니다.</td></tr>')
        + f"</tbody></table><nav class='catalog-pagination' aria-label='페이지 이동'><span>{data['page']} / {data['pages']} 페이지</span>"
        + (f"<a class='catalog-btn' href='{esc(link(data['page']-1))}'>{ui_icons.icon('chevron-left')}이전</a>" if data['page'] > 1 else '')
        + (f"<a class='catalog-btn' href='{esc(link(data['page']+1))}'>다음{ui_icons.icon('chevron-right')}</a>" if data['page'] < data['pages'] else '')
        + '</nav><script>' + CATALOG_SCRIPT + '</script></main></body></html>')
