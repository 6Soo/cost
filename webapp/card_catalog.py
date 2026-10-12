"""Owner-only, read-only listing of stored card transactions across all imports."""
import html
import re
from urllib.parse import urlencode

from . import ui_icons

PAGE_SIZE = 50
STATES = {'needs_review': '확인 필요', 'classified': '분류됨', 'booked': '장부 기록됨',
          'preserved': '기존 보존'}
TRADE_DATE = "COALESCE(NULLIF(t.approval_date,''),t.posting_date)"

CATALOG_STYLE = """
body{margin:0;background:#F7F9FC}
.card-catalog{max-width:1440px;margin:auto;color:#182230;
 font:400 14px/1.5 "Pretendard Variable",system-ui,sans-serif;word-break:keep-all}
.card-catalog *{box-sizing:border-box}
.card-catalog .catalog-actions{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 24px}
.card-catalog .catalog-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;
 min-height:42px;padding:9px 16px;border:1px solid #D0D5DD;border-radius:10px;background:#fff;
 color:#344054;font:inherit;font-weight:600;text-decoration:none;cursor:pointer;white-space:nowrap;
 box-shadow:0 1px 2px rgba(16,24,40,.05);transition:background .15s,border-color .15s}
.card-catalog .catalog-btn:hover{background:#F1F7F3;border-color:#1C7A52}
.card-catalog .catalog-btn.primary{background:#1C7A52;border-color:#1C7A52;color:#fff}
.card-catalog .catalog-btn.primary:hover{background:#166444}
.card-catalog h1{font-size:26px;letter-spacing:-.03em;margin:0 0 8px}
.card-catalog h1+p{color:#667085;max-width:800px;margin:0 0 16px;font-size:13px}
.card-catalog #card-count{display:inline-block;margin:0 0 16px;padding:6px 12px;
 border-radius:8px;background:#ECF5EF;color:#166444;font-weight:600;font-size:13px}
.card-catalog #card-filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:16px;
 margin:0 0 20px;background:#fff;border:1px solid #E4E7EC;border-radius:12px}
.card-catalog input,.card-catalog select{min-height:42px;max-width:100%;border:1px solid #D0D5DD;
 border-radius:8px;background:#fff;padding:8px 10px;color:#344054;font:inherit}
.card-catalog #card-filters input{flex:1 1 280px;min-width:0}
.card-catalog :focus-visible{outline:2px solid #2266F5;outline-offset:2px}
.card-catalog table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;
 border:1px solid #E4E7EC;border-radius:12px;overflow:hidden}
.card-catalog th,.card-catalog td{padding:12px;border-bottom:1px solid #E4E7EC;overflow-wrap:anywhere}
.card-catalog th{text-align:left;background:#F8FAFC;font-size:12px;color:#667085;vertical-align:top}
.card-catalog .header-button{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap;
 min-height:40px;padding:6px 8px;border:0;border-radius:7px;background:transparent;color:#344054;
 font:inherit;font-weight:600;cursor:pointer;text-align:left;transition:background .15s}
.card-catalog .header-button:hover,.card-catalog .header-button[aria-expanded=true]{background:#ECF5EF;color:#166444}
.card-catalog .header-button .ic{width:14px;height:14px;flex:0 0 auto;pointer-events:none}
.card-catalog .header-button .ic:last-child{margin-left:auto;color:#667085}
.card-catalog .catalog-btn .ic{width:16px;height:16px;flex:0 0 auto;pointer-events:none}
@media(prefers-reduced-motion:reduce){
 .card-catalog .catalog-btn,.card-catalog .header-button{transition:none}
}
.card-catalog .header-value{font-size:11px;color:#166444;font-weight:400}
.card-catalog .header-menu{position:fixed;inset:auto;margin:0;width:272px;max-width:calc(100vw - 24px);
 max-height:360px;overflow:auto;padding:8px;border:1px solid #E4E7EC;border-radius:12px;background:#fff;
 box-shadow:0 12px 28px rgba(16,24,40,.16);color:#344054;font:400 14px/1.5 "Pretendard Variable",system-ui,sans-serif}
.card-catalog .header-menu h2{font-size:12px;color:#667085;margin:6px 8px}
.card-catalog .filter-option{display:flex;align-items:center;justify-content:space-between;width:100%;
 min-height:40px;padding:8px 10px;border:0;border-radius:7px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}
.card-catalog .filter-option:hover{background:#F8FAFC}
.card-catalog .filter-option[aria-pressed=true]{background:#ECF5EF;color:#166444;font-weight:600}
.card-catalog .filter-option[aria-pressed=true]:after{content:'✓'}
.card-catalog tbody tr:last-child td{border-bottom:0}
.card-catalog tbody tr:hover{background:#F8FAFC}
.card-catalog td a{color:#166444;font-weight:600;text-underline-offset:3px}
.card-catalog .catalog-pagination{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:20px 0}
.card-catalog .catalog-pagination span{margin-right:auto;color:#667085}
@media(max-width:759px){
 .card-catalog .catalog-actions{margin:8px 0 18px}
 .card-catalog .catalog-actions .catalog-btn{flex:1 1 auto;padding:9px 12px}
 .card-catalog h1{font-size:22px}
 .card-catalog #card-filters{padding:12px;gap:8px}
 .card-catalog #card-filters input{flex-basis:100%;width:100%;font-size:16px}
 .card-catalog #card-filters .catalog-btn{flex:1}
 .card-catalog select{font-size:16px}
 .card-catalog table,.card-catalog tbody,.card-catalog tr,.card-catalog td{display:block}
 .card-catalog table{border:0;background:transparent;overflow:visible}
 .card-catalog thead{display:block;background:#fff;border:1px solid #E4E7EC;border-radius:12px;padding:10px}
 .card-catalog thead tr{display:flex;flex-wrap:wrap;gap:8px;margin:0;border:0}
 .card-catalog thead th{display:none}
 .card-catalog thead th.has-filter{display:block;flex:1 1 140px;min-width:0;border:0;padding:4px;background:transparent}
 .card-catalog tbody tr{margin:12px 0;border:1px solid #E4E7EC;border-radius:12px;background:#fff;overflow:hidden}
 .card-catalog td{display:grid;grid-template-columns:76px minmax(0,1fr);border:0;padding:8px 12px}
 .card-catalog td:before{content:attr(data-label);color:#667085;font-size:12px}
}
"""

CATALOG_SCRIPT = """(()=>{
 const form=document.getElementById('card-filters');
 document.querySelectorAll('.card-catalog .header-button').forEach(button=>{
   const panel=document.getElementById(button.getAttribute('popovertarget'));
   const position=()=>{const r=button.getBoundingClientRect();
     panel.style.left=Math.max(12,Math.min(r.left,innerWidth-panel.offsetWidth-12))+'px';
     panel.style.top=Math.max(12,Math.min(r.bottom+6,innerHeight-panel.offsetHeight-12))+'px';};
   panel.addEventListener('toggle',event=>{const open=event.newState==='open';
     button.setAttribute('aria-expanded',String(open));if(open)position();});
   window.addEventListener('resize',()=>{if(panel.matches(':popover-open'))position();});
 });
 document.querySelectorAll('.card-catalog .filter-option').forEach(button=>button.addEventListener('click',()=>{
   form.elements.namedItem(button.dataset.filter).value=button.dataset.value;
   form.requestSubmit();
 }));
})();"""


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
               'foreign_currency', 'item', 'description', 'classification_state', 'user_confirmed',
               'duplicate_of', 'conflict_reason', 'parse_error', 'display_tab_id', 'classification_source')
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
            + f" ORDER BY ({TRADE_DATE} IS NULL OR {TRADE_DATE}=''),{TRADE_DATE} {order},t.transaction_id"
            + ' LIMIT ? OFFSET ?', [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        cards = [r[0] for r in board.conn.execute('SELECT DISTINCT card_tail FROM transactions ORDER BY card_tail')]
        months = [r[0] for r in board.conn.execute(
            f"SELECT DISTINCT strftime('%Y-%m',{TRADE_DATE}) AS month FROM transactions t "
            'WHERE month IS NOT NULL ORDER BY month ASC')]
    return {'rows': [dict(zip((*columns, 'trip_name', 'company_excluded'), row)) for row in records],
            'total': total, 'all_count': all_count, 'cards': cards, 'months': months, 'page': page, 'pages': pages}


def render_html(data, query):
    esc = lambda value: html.escape('' if value is None else str(value), quote=True)
    value = lambda key: str((query.get(key) or [''])[0])
    def link(page):
        return '/cards?' + urlencode({**{k: value(k) for k in ('q', 'card', 'state', 'month', 'sort')}, 'page': page})
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
                 ('분류', r['item'] or '미분류'), ('여행', r['trip_name'] or
                  (quarter['name'] + ' · 여행 외 비용' if quarter else '여행 확인 필요')), ('상태', state)]
        row = ''.join(f"<td data-label='{esc(label)}'>{esc(text)}</td>" for label, text in cells)
        rows.append('<tr>' + row + f"<td><a href='/import?{urlencode({'batch': r['batch_id']})}'>자료 검토</a></td></tr>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><title>카드 내역</title>"
        f"<style>{CATALOG_STYLE}</style></head><body><main class='card-catalog'>"
        "<nav class='catalog-actions' aria-label='카드 업무'>"
        f"<a class='catalog-btn primary' href='/import'>{ui_icons.icon('upload')}카드 가져오기·검토</a></nav>"
        "<h1>카드 내역</h1>"
        f"<p id='card-count'>전체 {data['all_count']:,}건 · 검색 결과 {data['total']:,}건</p>"
        "<form id='card-filters' method='get' action='/cards'><input name='q' aria-label='카드 내역 검색' placeholder='지급처·분류·설명·승인번호·여행 검색'"
        f" value='{esc(value('q'))}'><button class='catalog-btn primary' type='submit'>{ui_icons.icon('search')}검색</button>"
        f"<a class='catalog-btn' href='/cards'>{ui_icons.icon('rotate-ccw')}초기화</a>" + hidden_filters + "</form>"
        + "<table><thead><tr>" + date_heading + card_heading
        + ''.join(f"<th scope='col'>{s}</th>" for s in ('지급처', '구분', '원본 금액', '분류', '여행'))
        + state_heading + "<th scope='col'>검토</th>"
        + '</tr></thead><tbody>' + (''.join(rows) or '<tr><td colspan="9">조건에 맞는 카드 내역이 없습니다.</td></tr>')
        + f"</tbody></table><nav class='catalog-pagination' aria-label='페이지 이동'><span>{data['page']} / {data['pages']} 페이지</span>"
        + (f"<a class='catalog-btn' href='{esc(link(data['page']-1))}'>{ui_icons.icon('chevron-left')}이전</a>" if data['page'] > 1 else '')
        + (f"<a class='catalog-btn' href='{esc(link(data['page']+1))}'>다음{ui_icons.icon('chevron-right')}</a>" if data['page'] < data['pages'] else '')
        + '</nav><script>' + CATALOG_SCRIPT + '</script></main></body></html>')
