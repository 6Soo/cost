"""Owner-only, read-only listing of stored card transactions across all imports."""
import html
import re
from urllib.parse import urlencode

PAGE_SIZE = 50
STATES = {'needs_review': '확인 필요', 'classified': '분류됨', 'booked': '장부 기록됨',
          'preserved': '기존 보존'}
TRADE_DATE = "COALESCE(NULLIF(t.approval_date,''),t.posting_date)"


def catalog(board, query):
    value = lambda key: str((query.get(key) or [''])[0]).strip()
    q, card, state = value('q'), value('card'), value('state')
    month = value('month')
    if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', month):
        month = ''
    order = 'ASC' if value('sort') == 'asc' else 'DESC'
    try:
        page = max(1, int(value('page') or 1))
    except ValueError:
        page = 1
    columns = ('transaction_id', 'batch_id', 'approval_date', 'posting_date', 'issuer', 'card_tail',
               'transaction_direction', 'transaction_kind', 'merchant', 'amount_krw', 'foreign_amount',
               'foreign_currency', 'item', 'description', 'classification_state', 'user_confirmed',
               'duplicate_of', 'conflict_reason', 'parse_error')
    where, params = [], []
    if q:
        where.append("(instr(lower(t.merchant || ' ' || t.item || ' ' || t.description || ' ' || "
                     "t.approval_number || ' ' || COALESCE(p.display_key,'')),lower(?))>0)")
        params.append(q)
    if card:
        where.append('t.card_tail=?')
        params.append(card)
    if state:
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
        all_count = board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
        total = board.conn.execute('SELECT COUNT(*)' + source + clause, params).fetchone()[0]
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        records = board.conn.execute('SELECT ' + ','.join('t.' + c for c in columns)
            + ',COALESCE(p.display_key,\'\'),COALESCE(e.excluded,0)' + source + clause
            + f" ORDER BY {TRADE_DATE} {order},t.transaction_id"
            + ' LIMIT ? OFFSET ?', [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        cards = [r[0] for r in board.conn.execute('SELECT DISTINCT card_tail FROM transactions ORDER BY card_tail')]
        months = [r[0] for r in board.conn.execute(
            f"SELECT DISTINCT strftime('%Y-%m',{TRADE_DATE}) AS month FROM transactions t "
            'WHERE month IS NOT NULL ORDER BY month DESC')]
    return {'rows': [dict(zip((*columns, 'trip_name', 'company_excluded'), row)) for row in records],
            'total': total, 'all_count': all_count, 'cards': cards, 'months': months, 'page': page, 'pages': pages}


def render_html(data, query):
    esc = lambda value: html.escape('' if value is None else str(value), quote=True)
    value = lambda key: str((query.get(key) or [''])[0])
    def option(key, label, selected):
        return f"<option value='{esc(key)}'{' selected' if key == selected else ''}>{esc(label)}</option>"
    def link(page):
        return '/cards?' + urlencode({**{k: value(k) for k in ('q', 'card', 'state', 'month', 'sort')}, 'page': page})
    def dropdown(name, label, options, selected):
        return (f"<select name='{name}' aria-label='{label}' form='card-filters' "
                "onchange='this.form.requestSubmit()'>"
                + ''.join(option(k, text, selected) for k, text in options) + '</select>')
    date_controls = dropdown('sort', '거래일 정렬', [('desc', '내림차순 · 최신 거래 먼저'), ('asc', '오름차순 · 오래된 거래 먼저')],
                             'asc' if value('sort') == 'asc' else 'desc')
    date_controls += dropdown('month', '조회 월', [('', '전체 월')]
                              + [(m, m.replace('-', '년 ') + '월') for m in data.get('months', [])], value('month'))
    card_control = dropdown('card', '카드 선택', [('', '모든 카드')]
                            + [(c, c) for c in data['cards'] if c], value('card'))
    state_control = dropdown('state', '분류 상태', [('', '모든 상태'), *STATES.items()], value('state'))
    rows = []
    for r in data['rows']:
        state = STATES.get(r['classification_state'], r['classification_state'])
        if r['user_confirmed']:
            state += ' · 사용자 확정'
        if r['duplicate_of']:
            state += ' · 중복'
        if r['company_excluded']:
            state += ' · 회사 경비 제외'
        if r['conflict_reason'] or r['parse_error']:
            state += ' · 오류 확인'
        direction = {'purchase': '결제', 'cancellation': '취소', 'refund': '환불'}.get(
            r['transaction_direction'], r['transaction_direction'])
        amount = f"{r['amount_krw']:,}원" if type(r['amount_krw']) is int else '금액 미확인'
        cells = [('거래일', r['approval_date'] or r['posting_date']),
                 ('카드', r['issuer'] + ' · ' + r['card_tail']), ('지급처', r['merchant']),
                 ('구분', direction + ' · ' + r['transaction_kind']), ('원본 금액', amount),
                 ('분류', r['item'] or '미분류'), ('여행', r['trip_name'] or '미배정'), ('상태', state)]
        row = ''.join(f"<td data-label='{esc(label)}'>{esc(text)}</td>" for label, text in cells)
        rows.append('<tr>' + row + f"<td><a href='/import?{urlencode({'batch': r['batch_id']})}'>자료 검토</a></td></tr>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><title>전체 카드 내역</title>"
        "<style>*{box-sizing:border-box}body{font-family:system-ui;margin:16px;color:#202521;background:#f7f8f7}"
        "main{max-width:1440px;margin:auto}nav,form{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}"
        "input,select,button,a{font:inherit;min-height:44px;max-width:100%;padding:8px}a{color:#166444}"
        "table{width:100%;border-collapse:collapse;background:white}th,td{padding:10px;border:1px solid #ddd;overflow-wrap:anywhere}"
        "thead select{display:block;width:100%;margin-top:6px}th{text-align:left}"
        "@media(max-width:759px){table,tbody,tr,td{display:block}thead{display:block}"
        "thead tr{display:flex;flex-wrap:wrap;gap:8px}thead th{display:none}thead th.has-filter{display:block;flex:1 1 140px;min-width:0}"
        "tr{margin:12px 0;border:1px solid #ddd}"
        "td{border:0;display:grid;grid-template-columns:76px minmax(0,1fr)}td:before{content:attr(data-label);color:#667085}"
        "input{width:100%}}</style></head><body><main>"
        "<nav><a href='/'>홈</a><a href='/board'>여행 장부</a><a href='/import'>카드 가져오기·검토</a></nav>"
        "<h1>전체 카드 내역</h1><p>DB에 저장된 모든 카드 거래입니다. 업로드 파일이나 검토 기간으로 제외하지 않습니다. "
        "취소·환불·중복·회사 경비도 포함하며, 원본 금액은 확정 지출 합계와 다를 수 있습니다.</p>"
        f"<p id='card-count'>전체 {data['all_count']:,}건 · 검색 결과 {data['total']:,}건</p>"
        "<form id='card-filters' method='get' action='/cards'><input name='q' aria-label='카드 내역 검색' placeholder='지급처·분류·설명·승인번호·여행 검색'"
        f" value='{esc(value('q'))}'><button type='submit'>검색</button><a href='/cards'>초기화</a></form>"
        + "<table><thead><tr><th class='has-filter' scope='col'>거래일" + date_controls
        + "</th><th class='has-filter' scope='col'>카드" + card_control + '</th>'
        + ''.join(f"<th scope='col'>{s}</th>" for s in ('지급처', '구분', '원본 금액', '분류', '여행'))
        + "<th class='has-filter' scope='col'>상태" + state_control + "</th><th scope='col'>검토</th>"
        + '</tr></thead><tbody>' + (''.join(rows) or '<tr><td colspan="9">조건에 맞는 카드 내역이 없습니다.</td></tr>')
        + f"</tbody></table><nav aria-label='페이지 이동'><span>{data['page']} / {data['pages']} 페이지</span>"
        + (f"<a href='{esc(link(data['page']-1))}'>이전</a>" if data['page'] > 1 else '')
        + (f"<a href='{esc(link(data['page']+1))}'>다음</a>" if data['page'] < data['pages'] else '')
        + '</nav></main></body></html>')
