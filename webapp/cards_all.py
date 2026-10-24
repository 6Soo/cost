"""Card all transactions page - year selector, month grid, expandable details."""
import html
import re
from urllib.parse import urlencode

from app.db import decided_sql
from . import ui_icons

from .card_catalog import TRADE_DATE
from app.review_holds import active_holds
from .refund_tab import groups
from .card_actions import next_action, GROUP_LABELS
from .card_flow import CardFlow
from app import quarter_costs

# CSS styles for the card all transactions page
CARDS_ALL_STYLE = """
.cards-all{font:400 14px/1.5 "Pretendard Variable",system-ui,sans-serif;color:var(--ink);word-break:keep-all;max-width:1440px;margin:auto;padding:0 16px}
.cards-all *{box-sizing:border-box}
.cards-all h1{font-size:26px;letter-spacing:-.03em;margin:0 0 8px}
.cards-all .page-desc{color:var(--mut);font-size:13px;margin:0 0 20px}
.cards-all .year-selector{display:flex;align-items:center;gap:8px;margin:0 0 20px}
.cards-all .year-selector label{font-weight:600;white-space:nowrap}
.cards-all .year-selector select{min-height:42px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--ink);font:inherit}
.cards-all .month-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 24px}
@media(max-width:900px){.cards-all .month-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.cards-all .month-grid{grid-template-columns:repeat(2,1fr)}}
.cards-all .month-tile{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:120px;padding:16px;border:1px solid var(--line);border-radius:12px;background:var(--paper);cursor:pointer;text-decoration:none;color:var(--ink);transition:border-color .15s,background .15s,box-shadow .15s}
.cards-all .month-tile:hover{border-color:var(--grn);box-shadow:0 4px 12px rgba(28,122,82,.15)}
.cards-all .month-tile:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.cards-all .month-tile.selected{border-color:var(--grn);background:var(--grn-lt);box-shadow:0 0 0 2px var(--grn)}
.cards-all .month-tile .month-name{font-size:18px;font-weight:600;margin-bottom:4px}
.cards-all .month-tile .month-count{font-size:13px;color:var(--mut)}
.cards-all .month-tile .month-count.zero{color:var(--text-muted)}
.cards-all .month-detail{margin-top:16px;padding:16px;border:1px solid var(--line);border-radius:12px;background:var(--paper)}
.cards-all .month-detail-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.cards-all .month-detail-header h2{font-size:20px;margin:0}
.cards-all .month-detail-header .close-btn{min-height:36px;padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--ink);font:inherit;cursor:pointer}
.cards-all .month-detail-header .close-btn:hover{background:var(--hover)}
.cards-all .transactions-table{width:100%;border-collapse:separate;border-spacing:0}
.cards-all .transactions-table th,.cards-all .transactions-table td{padding:10px 12px;border-bottom:1px solid var(--line2);text-align:left}
.cards-all .transactions-table th{font-size:12px;color:var(--mut);font-weight:600;background:var(--surface-muted)}
.cards-all .transactions-table tbody tr:hover{background:var(--hover)}
.cards-all .transactions-table .date-group td{background:var(--surface-muted);font-weight:600;font-size:13px;border-top:2px solid var(--line)}
.cards-all .transactions-table .amount{font-variant-numeric:tabular-nums;text-align:right}
.cards-all .transactions-table .trip-assigned{color:var(--grn);font-weight:500}
.cards-all .transactions-table .trip-unassigned{color:var(--mut)}
.cards-all .transactions-table .trip-inferred{color:var(--warn)}
.cards-all .transactions-table .status-badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600}
.cards-all .transactions-table .status-cancelled{background:var(--neg);color:#fff}
.cards-all .transactions-table .status-refund{background:var(--warn);color:#fff}
.cards-all .transactions-table .status-conflict{background:var(--bad);color:#fff}
.cards-all .empty-state{text-align:center;padding:40px;color:var(--mut)}
.cards-all .empty-state .icon{font-size:48px;margin-bottom:12px;opacity:.5}
.cards-all .transaction-row{cursor:pointer}
.cards-all .transaction-row:focus-visible{outline:2px solid var(--focus);outline-offset:-2px}
"""

CARDS_ALL_SCRIPT = """(()=>{
  const grid=document.querySelector('.month-grid');
  const detail=document.querySelector('.month-detail');
  if(!grid||!detail)return;
  let selectedMonth=null;
  function closeDetail(){
    detail.style.display='none';
    detail.innerHTML='';
    grid.querySelectorAll('.month-tile').forEach(t=>t.classList.remove('selected'));
    selectedMonth=null;
    history.replaceState(null,'',location.pathname+'?year='+yearSelect.value);
  }
  grid.addEventListener('click',e=>{
    const tile=e.target.closest('.month-tile');
    if(!tile)return;
    const month=tile.dataset.month;
    if(selectedMonth===month){
      closeDetail();
      return;
    }
    selectedMonth=month;
    grid.querySelectorAll('.month-tile').forEach(t=>t.classList.toggle('selected',t.dataset.month===month));
    detail.style.display='block';
    detail.innerHTML='<div class="loading">불러오는 중...</div>';
    fetch('/api/cards/transactions?year='+yearSelect.value+'&month='+month,{credentials:'same-origin'})
      .then(r=>r.json())
      .then(data=>{detail.innerHTML=renderMonthDetail(data,month);})
      .catch(()=>{detail.innerHTML='<p class="empty-state">데이터를 불러올 수 없습니다.</p>';});
    history.replaceState(null,'',location.pathname+'?year='+yearSelect.value+'&month='+month);
  });
  const yearSelect=document.querySelector('.year-selector select');
  if(yearSelect){
    yearSelect.addEventListener('change',()=>{
      closeDetail();
      location.search='year='+yearSelect.value;
    });
  }
  document.addEventListener('click',e=>{
    if(e.target.matches('.month-detail-header .close-btn'))closeDetail();
  });
  function renderMonthDetail(data,month){
    if(!data.rows||!data.rows.length){
      return '<div class="empty-state"><div class="icon">📭</div><p>이 달에 저장된 카드 거래가 없습니다.</p></div>';
    }
    let html='<div class="month-detail-header"><h2>'+month.replace('-','년 ')+'월 · '+data.total+'건</h2><button type="button" class="close-btn">닫기</button></div>';
    html+='<table class="transactions-table"><thead><tr><th scope="col">이용일시</th><th scope="col">가맹점명</th><th scope="col" class="amount">금액</th><th scope="col">배정된 여행</th></tr></thead><tbody>';
    let currentDate=null;
    data.rows.forEach(row=>{
      const date=row.date_only;
      if(date!==currentDate){
        currentDate=date;
        const dayCount=data.dates[date]||0;
        html+='<tr class="date-group"><td colspan="4">'+date.replace(/-/g,'년 ').replace('-','월 ').replace('-','일')+' · '+dayCount+'건</td></tr>';
      }
      const time=row.time_only||'';
      const datetime=date+(time?' '+time:'');
      let tripClass='trip-unassigned';
      let tripText='미배정';
      if(row.trip_name){
        if(row.trip_inferred){
          tripClass='trip-inferred';
          tripText='추정: '+row.trip_name;
        }else{
          tripClass='trip-assigned';
          tripText=row.trip_name;
        }
      }
      let statusHtml='';
      if(row.is_cancelled)statusHtml+='<span class="status-badge status-cancelled">취소</span> ';
      if(row.is_refund)statusHtml+='<span class="status-badge status-refund">환불</span> ';
      if(row.has_conflict)statusHtml+='<span class="status-badge status-conflict">충돌</span> ';
      html+='<tr class="transaction-row" tabindex="0" data-href="'+row.detail_url+'">'
        +'<td>'+datetime+'</td>'
        +'<td>'+row.merchant+'</td>'
        +'<td class="amount">'+row.amount_display+'</td>'
        +'<td class="'+tripClass+'">'+tripText+statusHtml+'</td>'
        +'</tr>';
    });
    html+='</tbody></table>';
    return html;
  }
  const params=new URLSearchParams(location.search);
  const initialMonth=params.get('month');
  if(initialMonth){
    const tile=grid.querySelector('.month-tile[data-month="'+initialMonth+'"]');
    if(tile)tile.click();
  }
  document.addEventListener('keydown',e=>{
    if(e.key==='Enter'||e.key===' '){
      const row=e.target.closest('.transaction-row');
      if(row&&row.dataset.href){
        e.preventDefault();
        location.href=row.dataset.href;
      }
    }
  });
})();"""


def get_available_years(board):
    """Return sorted list of years that have transactions."""
    with board._lock:
        rows = board.conn.execute(
            f"SELECT DISTINCT strftime('%Y', {TRADE_DATE}) AS year FROM transactions t "
            f"WHERE {TRADE_DATE} IS NOT NULL AND {TRADE_DATE} != '' ORDER BY year ASC"
        ).fetchall()
    years = [r[0] for r in rows if r[0]]
    if '2026' not in years:
        years.insert(0, '2026')
    return years


def get_year_month_counts(board, year):
    """Return dict of month->count for a given year, including 0-count months."""
    with board._lock:
        rows = board.conn.execute(
            f"SELECT strftime('%m', {TRADE_DATE}) AS month, COUNT(*) AS cnt FROM transactions t "
            f"WHERE strftime('%Y', {TRADE_DATE}) = ? AND {TRADE_DATE} IS NOT NULL AND {TRADE_DATE} != '' "
            "GROUP BY month ORDER BY month ASC",
            (year,)
        ).fetchall()
    counts = {f"{year}-{r[0]}": r[1] for r in rows}
    # Ensure all 12 months present
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        if key not in counts:
            counts[key] = 0
    return counts


def get_month_transactions(board, year, month):
    """Return transactions for a specific year/month with date grouping."""
    month_str = f"{year}-{month:02d}"
    columns = ('transaction_id', 'batch_id', 'approval_date', 'posting_date', 'issuer', 'card_tail',
               'transaction_direction', 'transaction_kind', 'merchant', 'amount_krw', 'foreign_amount',
               'foreign_currency', 'item', 'description', 'classification_state', 'decided',
               'duplicate_of', 'conflict_reason', 'parse_error', 'display_tab_id', 'classification_source')
    from .history_policy import cutoff
    boundary = cutoff()
    base = f"({TRADE_DATE} IS NULL OR {TRADE_DATE}='' OR {TRADE_DATE}>=?)" if boundary else ''
    where, params = ([base], [boundary]) if base else ([], [])
    where.append(f"strftime('%Y-%m',{TRADE_DATE})=?")
    params.append(month_str)
    clause = ' WHERE ' + ' AND '.join(where) if where else ''
    source = (' FROM transactions t LEFT JOIN trip_tabs p ON p.tab_id=t.display_tab_id'
              ' LEFT JOIN transaction_company_exclusions e ON e.transaction_id=t.transaction_id')
    with board._lock:
        records = board.conn.execute(
            'SELECT ' + ','.join(decided_sql('t') if c == 'decided' else 't.' + c for c in columns)
            + ',COALESCE(p.display_key,\'\'),COALESCE(e.excluded,0)' + source + clause
            + f" ORDER BY ({TRADE_DATE} IS NULL OR {TRADE_DATE}=''),{TRADE_DATE} ASC,t.transaction_id",
            params
        ).fetchall()
    rows = [dict(zip((*columns, 'trip_name', 'company_excluded'), row)) for row in records]

    complete = {r['transaction_id'] for group in groups(board) for r in group}
    for row in rows:
        if row['transaction_id'] in complete:
            row['trip_name'] = '환불'
    holds = active_holds(board.conn)
    booked = {r[0] for r in board.conn.execute('SELECT transaction_id FROM ledger_entries')}
    for row in rows:
        row['review_hold'] = holds.get(row['transaction_id'])
        row['next_action'] = next_action(row, {'already_booked': row['transaction_id'] in booked})
    if any(re.search(r'toyoko|토요코인', row.get('merchant') or '', re.I) for row in rows):
        notes = CardFlow(board)._ota_candidate_notes(rows)
        for row in rows:
            row['ota_candidate_notes'] = notes.get(row['transaction_id'], [])

    # Build date-only and time-only fields, and detail URLs
    result_rows = []
    date_counts = {}
    for r in rows:
        trade_date = r['approval_date'] or r['posting_date']
        date_only = trade_date[:10] if trade_date else ''
        time_only = trade_date[11:16] if trade_date and len(trade_date) > 11 else ''
        if date_only:
            date_counts[date_only] = date_counts.get(date_only, 0) + 1

        action = r.get('next_action') or next_action(r)
        detail_url = action['href']

        # Trip assignment
        trip_inferred = False
        trip_name = r.get('trip_name')
        if r['decided']:
            pass  # user confirmed
        elif trip_name and trip_name not in ('환불', '여행 확인 필요'):
            if r.get('classification_source') == 'auto_inferred':
                trip_inferred = True

        # Amount display
        if type(r['amount_krw']) is int:
            amount_display = f"{r['amount_krw']:,}원"
        else:
            amount_display = '금액 미확인'

        # Status badges
        is_cancelled = r['transaction_direction'] == 'cancellation'
        is_refund = r['transaction_direction'] == 'refund'
        has_conflict = bool(r['conflict_reason'] or r['parse_error'] or r['duplicate_of'])

        result_rows.append({
            'transaction_id': r['transaction_id'],
            'date_only': date_only,
            'time_only': time_only,
            'merchant': r['merchant'] or '가맹점 미상',
            'amount_display': amount_display,
            'trip_name': trip_name,
            'trip_inferred': trip_inferred,
            'detail_url': detail_url,
            'is_cancelled': is_cancelled,
            'is_refund': is_refund,
            'has_conflict': has_conflict,
        })

    return {
        'rows': result_rows,
        'dates': date_counts,
        'total': len(result_rows),
        'month': month_str,
    }


def render_cards_all_html(data, query, *, csrf=''):
    """Render the card all transactions page with year selector and month grid."""
    esc = lambda value: html.escape('' if value is None else str(value), quote=True)
    value = lambda key: str((query.get(key) or [''])[0])

    selected_year = value('year') or '2026'
    available_years = data.get('years', ['2026'])
    month_counts = data.get('month_counts', {})

    year_options = ''.join(f"<option value='{esc(y)}'{' selected' if y == selected_year else ''}>{esc(y)}년</option>" for y in available_years)

    month_names = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
    month_tiles = []
    for i, name in enumerate(month_names, 1):
        month_key = f"{selected_year}-{i:02d}"
        count = month_counts.get(month_key, 0)
        count_class = ' zero' if count == 0 else ''
        month_tiles.append(
            f"<button type='button' class='month-tile' data-month='{esc(month_key)}' aria-pressed='false'>"
            f"<span class='month-name'>{esc(name)}</span>"
            f"<span class='month-count{count_class}'>{count:,}건</span>"
            f"</button>"
        )

    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><title>카드 전체 내역</title>"
        f"<style>{CARDS_ALL_STYLE}</style></head>"
        f"<body><main class='cards-all'>"
        f"<h1>카드 전체 내역</h1>"
        f"<p class='page-desc'>연도별 전체 카드 거래를 월별로 조회합니다. 타일을 눌러 상세를 확인하세요.</p>"
        f"<div class='year-selector'><label for='year-select'>연도</label>"
        f"<select id='year-select' name='year' onchange='this.form.submit()'>{year_options}</select></div>"
        f"<div class='month-grid' role='list' aria-label='월별 거래 건수'>{''.join(month_tiles)}</div>"
        f"<div class='month-detail' style='display:none' aria-live='polite'></div>"
        f"<script>{CARDS_ALL_SCRIPT}</script></main></body></html>")


def cards_all_page(board, query, *, csrf=''):
    """Main entry point for /cards/all route."""
    years = get_available_years(board)
    year = str((query.get('year') or ['2026'])[0]).strip()
    if year not in years:
        year = '2026'
    month_counts = get_year_month_counts(board, year)
    return render_cards_all_html({
        'years': years,
        'month_counts': month_counts,
    }, query, csrf=csrf)