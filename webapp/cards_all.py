"""카드 전체 내역 화면: 저장된 카드 원행을 연도/월 단위로 조회한다.

읽기 전용 화면이다. 원본/장부/OTA/Google 자료를 쓰지 않으며, 카드사 원본 대비
누락을 자동 판정하지 않는다. 표시 필드는 `card_transactions` 읽기 투영이 실제로
돌려주는 값만 사용한다.
"""
from __future__ import annotations

import html
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from . import card_transactions as _ct
from . import ledger_design as _design
from . import ui_icons
from app import request_metrics

DEFAULT_YEAR = 2026
MIN_YEAR = 2000
MAX_YEAR = 2100
PAGE_SIZE = 100
UNDATED_PAGE_SIZE = 100

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_CURSOR_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}(?:[T ].*)?)?\|.+$")
_TIME_RE = re.compile(r"^(\d{2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?$")


CARD_ALL_STYLE = """
<style id="card-all-design">
/* This visual layer scopes every rule to the read-only card history screen. */
.card-all-page{--ca-border:var(--line,#e2e8f0);--ca-muted:var(--mut,#64748b);--ca-ink:var(--ink,#0f172a);--ca-paper:var(--paper,#fff);--ca-soft:var(--hover,#f1f5f9);--ca-accent:var(--grn,#1c7a52);color:var(--ca-ink);max-width:1260px;margin:0 auto;padding:24px 24px 64px;font:inherit}
.card-all-page *{box-sizing:border-box}
.card-all-page .card-all-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;padding:22px 24px;border:1px solid var(--ca-border);border-radius:16px;background:var(--ca-paper);margin-bottom:18px}
.card-all-page .card-all-eyebrow{font-size:12px;font-weight:750;letter-spacing:.045em;color:var(--ca-accent);margin:0 0 5px}
.card-all-page .card-all-lead{font-size:15px;font-weight:700;margin:0}
.card-all-page .card-all-description{font-size:12px;color:var(--ca-muted);margin:5px 0 0;max-width:52ch;line-height:1.55}
.card-all-page .card-all-summary{display:grid;grid-template-columns:repeat(2,minmax(110px,1fr));gap:10px}
.card-all-page .card-all-stat{display:grid;gap:3px;min-width:115px;padding:12px 15px;border:1px solid var(--ca-border);background:var(--ca-soft);border-radius:11px}
.card-all-page .card-all-stat-label{font-size:11px;color:var(--ca-muted);font-weight:650}
.card-all-page .card-all-stat-value{font-size:19px;font-variant-numeric:tabular-nums;font-weight:800}
.card-all-page .card-all-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 12px;flex-wrap:wrap}
.card-all-page .card-all-toolbar-title{font-size:16px;font-weight:750;margin:0}











.card-all-page :is(button,a,select):focus-visible{outline:2px solid var(--focus,#2563eb);outline-offset:3px}
.card-all-page :is(.card-all-detail,.card-all-undated,.card-all-prompt){border:1px solid var(--ca-border);border-radius:14px;background:var(--ca-paper);padding:19px 20px;margin:0 0 16px}
.card-all-page :is(.card-all-detail,.card-all-undated) h2{margin:0 0 14px;font-size:16px;font-weight:750;line-height:1.5}
.card-all-page .card-all-prompt{color:var(--ca-muted);font-size:13px}
.card-all-page .card-all-muted{font-size:12px;line-height:1.6;color:var(--ca-muted)}
.card-all-page .card-all-table-wrap{width:100%;min-width:0;border-radius:10px;border:1px solid var(--ca-border)}
.card-all-page .card-all-table{table-layout:fixed;border-collapse:separate;border-spacing:0;width:100%;min-width:0;background:var(--ca-paper);font-size:13px;line-height:1.4}
.card-all-page .card-all-table .date-column{width:17%}
.card-all-page .card-all-table .merchant-column{width:32%}
.card-all-page .card-all-table .amount-column{width:24%}
.card-all-page .card-all-table .trip-column{width:27%}
.card-all-page .card-all-table th,.card-all-page .card-all-table td{padding:7px 6px;text-align:left;vertical-align:middle;border:0;overflow-wrap:anywhere}
.card-all-page .card-all-table thead th{position:sticky;top:0;background:var(--ca-soft);color:var(--ca-muted);font-size:12px;font-weight:700;z-index:1}
.card-all-page .card-all-table .date-group th{padding:9px 14px;background:var(--ca-soft);color:var(--ca-ink);font-size:12px;font-weight:750}
.card-all-page .card-all-table tbody tr:not(.date-group):hover{background:var(--ca-soft)}
.card-all-page .card-all-table tbody tr:last-child td{border-bottom:0}
.card-all-page .card-all-table .amount{text-align:right;font-weight:750;font-variant-numeric:tabular-nums}
.card-all-page .card-all-table .amount-cell .amount{white-space:normal;overflow-wrap:anywhere}
.card-all-page .card-all-table .use-datetime{font-variant-numeric:tabular-nums;white-space:normal;color:var(--ca-muted)}
.card-all-page .card-all-table .merchant{font-weight:700;overflow-wrap:anywhere}
.card-all-page .card-all-table .merchant{min-width:0}
.card-all-page .card-all-table tr[data-detail-id]{cursor:pointer}
.card-all-page .card-all-table tr[data-detail-id]:focus-within{outline:2px solid var(--focus,#2563eb);outline-offset:-2px;background:var(--ca-soft)}
.card-all-page .card-all-row-toggle{display:block;width:100%;height:auto;min-height:0;margin:0;padding:0;border:0;border-radius:0;appearance:none;-webkit-appearance:none;background:none;color:inherit;text-align:left;font:inherit;line-height:inherit;cursor:pointer;overflow-wrap:anywhere;min-width:0}
.card-all-page .card-all-row-toggle:focus-visible{outline:2px solid var(--focus,#2563eb);outline-offset:2px}
.card-all-page .card-all-expanded td{padding:12px;background:var(--ca-soft)}
.card-all-page .card-all-expanded[hidden]{display:none}
.card-all-page .card-all-expanded-content{min-width:0;overflow-wrap:anywhere}
.card-detail-fields{display:grid;grid-template-columns:minmax(60px,auto) minmax(0,1fr);gap:8px 12px;margin:0;font-size:12px;line-height:1.5}
.card-detail-fields dt{color:var(--mut,#64748b)}
.card-detail-fields dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;min-width:0}
.card-all-page .card-all-loading{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ca-muted)}
.card-all-spinner{display:inline-block;width:18px;height:18px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:card-all-spin .7s linear infinite;flex-shrink:0}
@keyframes card-all-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.card-all-spinner{animation-duration:1.8s}}
.card-all-page .card-all-page-loading{position:fixed;inset:0;z-index:1000;background:var(--ca-paper);opacity:.94;display:flex;align-items:center;justify-content:center;gap:10px}
.card-all-page .card-all-page-loading[hidden]{display:none}
.card-all-page .card-identity{display:block;font-size:12px;line-height:1.5;font-weight:500;color:var(--ca-muted);margin-top:4px}
.card-all-page .card-all-table .amount-cell{text-align:right}
.card-all-page .card-all-table .amount-cell .amount{text-align:right;font-weight:750;font-variant-numeric:tabular-nums}
.card-all-page .card-all-table .amount-cell .card-all-badges{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:3px}
.card-all-page .card-all-filters{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 16px;font-size:13px}
.card-all-page .card-all-filters>label{display:inline-flex;align-items:center;gap:7px;min-width:0}
.card-all-page .card-all-filters :is(input[type=search],select){min-height:42px;max-width:100%;padding:8px;border:1px solid var(--ca-border);border-radius:8px;background:var(--ca-paper);color:var(--ca-ink);font:inherit}
.card-all-page .card-all-filters input[type=search]{width:min(360px,100%)}
.card-all-page .card-all-filters button{min-height:42px;padding:8px 14px;font:inherit}
.card-all-page .card-all-table .trip{min-width:0;overflow-wrap:anywhere}
.card-all-page .card-all-trip-name{display:block;font-weight:700;line-height:1.4}
.card-all-page .card-all-trip-name.unassigned{color:var(--ca-muted);font-weight:500}
.card-all-page .card-all-trip-source{display:inline-flex;margin-top:4px;font-size:11px;line-height:1.5;color:var(--ca-muted)}
.card-all-page .card-all-badge{display:inline-flex;margin:5px 0 0;padding:2px 7px;border-radius:6px;border:1px solid var(--ca-border);background:var(--ca-soft);font-size:11px;color:var(--ca-ink)}
.card-all-page .card-all-link{color:var(--ca-accent);font-weight:750;font-size:12px;text-decoration:underline;text-underline-offset:3px}
.card-all-page .card-all-table .card-all-link{display:inline-flex;white-space:normal;overflow-wrap:anywhere;margin-top:6px}
.card-all-page .card-all-pagination{margin-top:15px;display:flex;justify-content:center}
.card-all-page .card-all-pagination a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:10px 16px;border:1px solid var(--ca-border);border-radius:9px;background:var(--ca-soft);text-decoration:none}
.card-all-page .card-all-help{margin:0 0 16px;font-size:12px;color:var(--ca-muted)}
.card-all-page .card-all-help summary{cursor:pointer;min-height:44px;align-content:center;width:fit-content}
.card-all-page .card-all-help p{margin:0 0 12px;max-width:80ch}
/* Compact, flat card-history layout: one content plane with clear row separators. */
.card-all-page{padding:14px 18px 40px}
.card-all-page .card-all-hero{border:0;border-radius:0;background:transparent;padding:0 0 12px;margin:0 0 12px;border-bottom:1px solid var(--ca-border);gap:12px}
.card-all-page .card-all-eyebrow{display:none}
.card-all-page .card-all-lead{font-size:15px}
.card-all-page .card-all-summary{display:flex;gap:18px;align-items:baseline}
.card-all-page .card-all-stat{display:flex;gap:7px;align-items:baseline;min-width:0;padding:0;border:0;border-radius:0;background:transparent}
.card-all-page .card-all-stat-value{font-size:15px}
.card-all-page .card-all-toolbar{display:none}
.card-all-page .card-all-filters{margin:0 0 8px;gap:8px;padding:0;border:0;background:transparent}
.card-all-page .card-all-filters :is(input[type=search],select){min-height:42px;padding:6px 9px}
.card-all-page .card-all-filters button{min-height:44px}
.card-all-page .card-all-help{margin:0 0 10px}
.card-all-page .card-all-help summary{min-height:44px}
.card-all-page :is(.card-all-detail,.card-all-undated){border:0;border-radius:0;background:transparent;padding:0;margin:0 0 20px}
.card-all-page :is(.card-all-detail,.card-all-undated) h2{font-size:16px;margin:8px 0 10px}
.card-all-page .card-all-table-wrap{border:0;border-radius:0;overflow:visible}
.card-all-page .card-all-table{background:transparent}
.card-all-page .card-all-table thead th{background:transparent;border-bottom:1px solid var(--ca-border)}
.card-all-page .card-all-table tbody tr:not(.date-group):not(.card-all-expanded)>td{border-bottom:1px solid var(--ca-border)}
.card-all-page .card-all-table .date-group th{background:transparent;border-bottom:1px solid var(--ca-border)}
.card-all-page .card-all-table th,.card-all-page .card-all-table td{padding:10px 8px}
.card-all-page .card-all-table .card-all-expanded td{background:var(--ca-soft)}
@media(max-width:759px){
 .card-all-page{padding:8px 10px 30px}
 .card-all-page .card-all-hero{padding:0 0 8px;margin:0 0 10px;gap:6px}
 .card-all-page .card-all-lead{font-size:13px}
 .card-all-page .card-all-summary{width:auto;display:flex;gap:10px;flex-wrap:wrap}
 .card-all-page .card-all-stat{display:flex;gap:4px;padding:0}
 .card-all-page .card-all-stat-label{font-size:10px}
 .card-all-page .card-all-stat-value{font-size:12px}
 .card-all-page .card-all-filters{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;padding:0;border:0;border-radius:0;background:transparent;margin:0 0 5px}
 .card-all-page .card-all-filters>label{grid-column:auto;display:flex;flex-direction:column;align-items:stretch;gap:3px;font-size:11px}
 .card-all-page .card-all-filters>label:has(input[type=search]){grid-column:1/-1}
 .card-all-page .card-all-filters>.card-all-unassigned{grid-column:1/-1;display:flex;flex-direction:row;align-items:center;min-height:44px;font-size:12px}
 .card-all-page .card-all-filters input[type=checkbox]{width:20px;height:20px;accent-color:var(--ca-accent);flex-shrink:0}
 .card-all-page .card-all-filters :is(input[type=search],select){min-height:44px;font-size:16px;padding:5px 8px}
 .card-all-page .card-all-filters button,.card-all-page .card-all-filters>.card-all-link{grid-column:auto;width:100%;min-height:44px;padding:5px 8px}
 .card-all-page .card-all-filters>.card-all-link{display:flex;align-items:center;justify-content:center}
 .card-all-page .card-all-help{padding:0;margin:0 0 8px}
 .card-all-page .card-all-detail,.card-all-page .card-all-undated{padding:0;margin:0 0 14px}
 .card-all-page :is(.card-all-detail,.card-all-undated) h2{font-size:15px;margin:6px 0 8px}
 .card-all-page .card-all-table-wrap{border:0;border-radius:0}
 .card-all-page .card-all-table{font-size:12px}
 .card-all-page .card-all-table th,.card-all-page .card-all-table td{padding:8px 4px}
 .card-all-page .card-all-table .date-column{width:14%}
 .card-all-page .card-all-table .merchant-column{width:36%}
 .card-all-page .card-all-table .amount-column{width:25%}
 .card-all-page .card-all-table .trip-column{width:25%}
 .card-all-page .card-all-table .merchant-name{font-size:12px;line-height:1.35}
 .card-all-page .card-identity{font-size:10px;margin-top:2px}
 .card-all-page .card-all-table .amount{font-size:12px}
 .card-all-page .card-all-table .card-all-link{min-height:44px;margin-top:0}
 .card-all-page .card-all-row-toggle{min-height:44px}
}

/* Mobile history is a two-line transaction list, not a squeezed four-column table. */
@media(max-width:759px){
 .card-all-page .card-all-table-wrap{width:100%;overflow:visible}
 .card-all-page .card-all-table,
 .card-all-page .card-all-table tbody{display:block;width:100%;table-layout:auto}
 .card-all-page .card-all-table colgroup,
 .card-all-page .card-all-table thead{display:none}
 .card-all-page .card-all-table tbody tr.date-group{display:block;margin:10px 0 0;border:0}
 .card-all-page .card-all-table tbody tr.date-group th{display:block;padding:7px 2px 5px;border:0;background:transparent;font-size:12px;font-weight:700;color:var(--ca-muted);text-align:left}
 .card-all-page .card-all-table tbody tr[data-tx-id]{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,46%);grid-template-areas:"merchant amount" "merchant trip";column-gap:12px;align-items:start;width:100%;min-height:44px;padding:6px 2px;border-bottom:1px solid var(--ca-border)}
 .card-all-page .card-all-table tbody tr[data-tx-id]>td{display:block;padding:0;border:0;min-width:0;vertical-align:initial}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.use-datetime{display:none}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.merchant{grid-area:merchant;font-size:13px;font-weight:700;line-height:1.35;overflow-wrap:anywhere}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.amount-cell{grid-area:amount;text-align:right;align-self:start}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.trip{grid-area:trip;align-self:end;text-align:right;font-size:11px;max-width:145px}
 .card-all-page .card-all-table .card-all-row-toggle{min-height:0}
 .card-all-page .card-all-table .merchant-name{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:1;overflow:hidden}
 .card-all-page .card-all-table .card-identity{display:block;margin-top:5px;font-size:11px;line-height:1.3;font-weight:400}
 .card-all-page .card-all-table .amount-cell .amount{font-size:14px;font-weight:750;white-space:normal;overflow-wrap:anywhere}
 .card-all-page .card-all-table .card-all-trip-name{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;line-height:1.35;font-weight:600}
 .card-all-page .card-all-table .card-all-trip-source{display:none}
 .card-all-page .card-all-table .card-all-badges{max-width:135px}
 .card-all-page .card-all-table tbody tr.card-all-expanded:not([hidden]){display:block;width:100%;border-bottom:1px solid var(--ca-border)}
 .card-all-page .card-all-table tbody tr.card-all-expanded>td{display:block;width:100%;padding:10px 4px}
 .card-all-page .card-all-table tbody tr.card-all-expanded[hidden]{display:none}
}

</style>
"""

CARD_ALL_SCRIPT = """
<script>
document.addEventListener('click', async function(event) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const target = event.target instanceof Element ? event.target : event.target.parentElement;
    const row = target && target.closest('.card-all-table tr[data-detail-id]');
    if (!row || window.getSelection().toString()) return;
    if (target.closest('a,input,select,textarea,summary') || (target.closest('button') && !target.closest('.card-all-row-toggle'))) return;
    const toggle = row.querySelector('.card-all-row-toggle');
    const detail = document.getElementById(toggle.getAttribute('aria-controls'));
    detail.hidden = !detail.hidden;
    toggle.setAttribute('aria-expanded', String(!detail.hidden));
    if (detail.hidden || detail.dataset.loaded || detail.dataset.loading) return;
    const content = detail.querySelector('.card-all-expanded-content');
    detail.dataset.loading = 'true';
    content.setAttribute('aria-busy', 'true');
    content.innerHTML = '<div class="card-all-loading" role="status"><span class="card-all-spinner" aria-hidden="true"></span>거래를 불러오는 중</div>';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    let failureMessage = '거래를 불러오지 못했습니다. 닫았다 다시 열어 주세요.';
    try {
        const response = await fetch('/api/cards/transactions/detail?' + new URLSearchParams({id:row.dataset.detailId}),
                                     {credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if (!response.ok) {
            failureMessage = response.status === 401 || response.status === 403 ? '로그인 상태를 확인한 뒤 다시 열어 주세요.' :
                             response.status === 404 ? '거래를 찾을 수 없습니다. 목록을 새로 조회해 주세요.' : failureMessage;
            throw new Error();
        }
        const data = await response.json();
        if (typeof data.html !== 'string') throw new Error();
        content.innerHTML = data.html;
        detail.dataset.loaded = 'true';
    } catch (error) {
        content.textContent = error.name === 'AbortError' ? '응답이 지연되고 있습니다. 닫았다 다시 열어 주세요.' : failureMessage;
    } finally {
        clearTimeout(timer);
        delete detail.dataset.loading;
        content.removeAttribute('aria-busy');
    }
});
document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape') return;
    const row = event.target.closest('.card-all-table tr');
    if (!row) return;
    const detail = row.classList.contains('card-all-expanded') ? row : row.nextElementSibling;
    if (!detail || !detail.classList.contains('card-all-expanded') || detail.hidden) return;
    detail.hidden = true;
    const toggle = detail.previousElementSibling.querySelector('.card-all-row-toggle');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.focus();
});
document.addEventListener('submit', function(event) {
    if (!event.target.matches('.card-all-filters')) return;
    document.querySelector('.card-all-page-loading').hidden = false;
});
document.addEventListener('click', function(event) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('.card-all-page a[href]');
    if (link && link.origin === location.origin && !link.target && !link.hasAttribute('download'))
        document.querySelector('.card-all-page-loading').hidden = false;
});
window.addEventListener('pageshow', function() {
    const loading = document.querySelector('.card-all-page-loading');
    if (loading) loading.hidden = true;
});
</script>
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _first(query_params: dict | None, key: str, default=None):
    if not query_params:
        return default
    values = query_params.get(key)
    if not values:
        return default
    return values[0]


def _filter_state(query_params):
    state = {}
    if _first(query_params, 'unassigned') == '1':
        state['unassigned'] = '1'
    for name in ('card', 'q'):
        value = str(_first(query_params, name, '') or '').strip()[:200]
        if value:
            state[name] = value
    return state


def _hidden_filters(state):
    return ''.join(f"<input type='hidden' name='{_esc(key)}' value='{_esc(value)}'>"
                   for key, value in (state or {}).items())


def _trip_context():
    """Use the same schedule validation as card classification, without writes."""
    from . import ledger_board
    from .card_flow import CardFlow
    from types import SimpleNamespace
    store = ledger_board._active_store()
    if store is None or ledger_board.current_role() != 'owner':
        return {}, set()
    trips = store.list_trips(include_archived=True)
    # trip_valid needs only the board and its optional in-memory title cache.
    # Avoid CardFlow.__init__: constructing a pipeline may initialize SQL schema.
    flow = SimpleNamespace(board=store)
    names = {str(trip['tab_id']): str(trip.get('display_key') or trip['tab_id']) for trip in trips}
    valid = {str(trip['tab_id']) for trip in trips if CardFlow.trip_valid(flow, trip['tab_id'])}
    return names, valid


def _safe_int(raw, default, minimum: int, maximum: int):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < minimum or value > maximum:
        return default
    return value


def _request_params(query_params: dict | None) -> tuple[int, int | None, str | None, str | None, bool]:
    """연도/월/커서를 검증한다. 잘못된 값은 안전한 기본값으로 되돌린다."""
    year = _safe_int(_first(query_params, "year", DEFAULT_YEAR), DEFAULT_YEAR,
                     MIN_YEAR, MAX_YEAR)
    month_raw = _first(query_params, "month")
    period = _first(query_params, 'period')
    if period is not None:
        if (not re.fullmatch(r'\d{4}(?:-(?:0[1-9]|1[0-2]))?', str(period))
                or not MIN_YEAR <= int(str(period)[:4]) <= MAX_YEAR):
            return DEFAULT_YEAR, None, None, None, False
        year = _safe_int(str(period)[:4], DEFAULT_YEAR, MIN_YEAR, MAX_YEAR)
        month_raw = str(period)[5:] or None
    month = None
    if month_raw is not None:
        month = _safe_int(month_raw, None, 1, 12)
        if month is None:
            # A malformed month must not fall through into another requested view.
            return year, None, None, None, False
    cursor = _first(query_params, "cursor")
    undated_cursor = _first(query_params, "undated_cursor")
    if cursor and not _CURSOR_RE.match(cursor):
        cursor = None
    if undated_cursor and not _CURSOR_RE.match(undated_cursor):
        undated_cursor = None
    show_undated = str(_first(query_params, "undated", "0")).strip() in ("1", "true", "on")
    # 월 상세와 날짜 미확인 상세는 함께 열지 않고, 명시한 날짜 미확인 모드를 우선한다.
    if show_undated:
        month = None
        cursor = None
    elif month is not None and cursor:
        undated_cursor = None
    elif undated_cursor:
        cursor = None
    return year, month, cursor, undated_cursor, show_undated


def _split_datetime(value) -> tuple[str, str]:
    """승인일 문자열을 (날짜, 시간)으로 나눈다.

    시간이 없거나 00:00이면 빈 문자열을 돌려준다. 없는 시간을 합성하지 않는다.
    """
    text = str(value or "").strip()
    if not text:
        return ("", "")
    match = _DATE_RE.match(text)
    if not match:
        return ("", "")
    date_part = match.group(0)
    rest = text[len(date_part):].strip()
    if rest[:1] in ("T", " "):
        rest = rest[1:].strip()
    time_match = _TIME_RE.match(rest)
    if not time_match:
        return (date_part, "")
    hour = int(time_match.group(1))
    minute = int(time_match.group(2))
    seconds = time_match.group(3)
    if hour > 23 or minute > 59:
        return (date_part, "")
    if seconds is not None and float(seconds) >= 60:
        return (date_part, "")
    return (date_part, time_match.group(0))


def _format_use_date(value) -> str:
    date_part, time_part = _split_datetime(value)
    if not date_part:
        return ""
    return f"{date_part} {time_part}" if time_part else date_part


def _format_number(value):
    """부호를 보존한 천 단위 구분 숫자. 숫자가 아니면 None."""
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    negative = number < 0
    number = abs(number)
    body = format(number, "f")
    if "." in body:
        whole, fraction = body.split(".", 1)
        fraction = fraction.rstrip("0")
    else:
        whole, fraction = body, ""
    whole = f"{int(whole):,}"
    result = f"{whole}.{fraction}" if fraction else whole
    return f"-{result}" if negative else result


def _format_amount(amount_krw, foreign_amount="", foreign_currency="") -> str:
    """원본 부호와 통화를 유지한다. 환산액으로 원본을 대체하지 않는다."""
    currency = str(foreign_currency or "").strip().upper()
    if currency and currency != "KRW":
        original = _format_number(foreign_amount)
        if original is not None:
            return f"{original} {currency}"
    krw = _format_number(amount_krw) if amount_krw is not None else None
    if krw is not None:
        return f"{krw}원"
    original = _format_number(foreign_amount)
    if original is not None and currency:
        return f"{original} {currency}"
    return "금액 미확인"


def _get_trip_display(trip_id, classification_source) -> str:
    """현재 유효한 배정과 출처만 표시한다. 확정/추정을 섞지 않는다."""
    trip = str(trip_id or "").strip()
    if not trip:
        return "미배정"
    source = str(classification_source or "").strip()
    if source == "manual":
        return f"{trip} · 사용자 확정"
    if source == "auto_inferred":
        return f"{trip} · 추정"
    return trip


def _classification_source_label(source) -> str:
    from app.assignment_status import classification_source_label
    return classification_source_label(source)


def _status_badges(item: dict) -> str:
    """읽기 투영이 실제로 돌려주는 상태만 배지로 표시한다."""
    badges: list[str] = []
    if str(item.get("duplicate_of") or "").strip():
        badges.append("<span class='card-all-badge duplicate'>중복 출처</span>")
    if str(item.get("conflict_reason") or "").strip():
        badges.append("<span class='card-all-badge conflict'>원본 충돌</span>")
    state = str(item.get("classification_state") or "").strip()
    if state == "needs_review":
        if item.get('batch_id') and item.get('transaction_id'):
            href = '/import?' + urlencode({'batch': item['batch_id'], 'transaction': item['transaction_id']})
            badges.append(f"<a class='card-all-badge review card-review-action' href='{_esc(href)}'>분류 검토</a>")
        else:
            badges.append("<span class='card-all-badge review'>검토 필요</span>")
    return "".join(badges)


def _detail_href(transaction_id) -> str:
    tid = str(transaction_id or "").strip()
    if not tid:
        return ""
    return "/board?" + urlencode({"row": f"card-{tid}"})


def _review_action(item: dict) -> str:
    """Open the existing revision/CSRF-protected editor for this exact source."""
    tid, batch = item.get('transaction_id'), item.get('batch_id')
    if not tid or not batch:
        return ""
    href = '/import?' + urlencode({'batch': batch, 'transaction': tid})
    if item.get('duplicate_of'):
        return f"<a class='card-all-link card-review-action' href='{_esc(href + '#preview')}'>중복 근거 확인</a>"
    label = ('원본 문제 확인' if item.get('conflict_reason') or item.get('parse_error') else
             '분류 수정' if item.get('classification_state') == 'classified' else '분류 검토')
    return f"<a class='card-all-link card-review-action' href='{_esc(href)}'>{label}</a>"


def card_detail_html(item: dict) -> str:
    """Escaped source facts; a ledger row is not required and nothing is written."""
    from app.assignment_status import assignment_conflict_label, row_assignment
    from app.quarter_tab import parse_tab
    assignment = row_assignment(item, _trip_context()[0].keys())
    destination = assignment['destination']
    quarter = parse_tab(destination)
    if quarter:
        destination = f'{quarter[0]}년 {quarter[1]}분기 기타비용'
    elif destination in ('', 'unclassified'):
        destination = '미배정'
    else:
        destination = _trip_context()[0].get(destination, destination)
    source = _classification_source_label(item.get('classification_source'))
    fields = [('가맹점', item.get('merchant')), ('이용일시', item.get('approval_date') or '날짜 확인 필요'),
              ('금액', _format_amount(item.get('amount_krw'), item.get('foreign_amount'), item.get('foreign_currency'))),
              ('카드', item.get('card_label')), ('승인번호', item.get('approval_number')),
              ('배정', destination), ('항목', item.get('item')), ('분류 출처', source),
              ('거래 내용', item.get('description')), ('중복 출처', item.get('duplicate_of')),
              ('원본 충돌', item.get('conflict_reason')),
              ('배정 충돌', assignment_conflict_label(assignment['conflicts']))]
    return "<dl class='card-detail-fields'>" + ''.join(
        f'<dt>{_esc(label)}</dt><dd>{_esc(value)}</dd>' for label, value in fields if value not in (None, '')) + '</dl>' + _review_action(item)


def _group_by_date(items: list[dict]) -> list[tuple[str, list[tuple[str, str, dict]]]]:
    """날짜 오름차순, 같은 날짜는 시간 있는 거래 먼저, 그다음 안정 ID 순."""
    grouped: dict[str, list[tuple[str, str, dict]]] = {}
    for item in items:
        date_part, time_part = _split_datetime(
            item.get("use_date") or item.get("approval_date"))
        key = date_part or "날짜 확인 필요"
        grouped.setdefault(key, []).append((date_part, time_part, item))
    ordered: list[tuple[str, list[tuple[str, str, dict]]]] = []
    for key in sorted(k for k in grouped if k != "날짜 확인 필요"):
        rows = grouped[key]
        rows.sort(key=lambda row: (row[1] == "", row[1],
                                   str(row[2].get("transaction_id") or "")))
        ordered.append((key, rows))
    if "날짜 확인 필요" in grouped:
        rows = sorted(grouped["날짜 확인 필요"],
                      key=lambda row: str(row[2].get("transaction_id") or ""))
        ordered.append(("날짜 확인 필요", rows))
    return ordered


def _period_date(value, year=None, month=None) -> str:
    """Shorten only the date context already stated by the selected period."""
    date_part, time_part = _split_datetime(value)
    if not date_part:
        return ''
    if year is None or int(date_part[:4]) != year:
        return _format_use_date(value)
    day = int(date_part[8:10])
    date_month = int(date_part[5:7])
    label = f'{day}일' if month == date_month else f'{date_month}월 {day}일'
    return f'{label} {time_part}' if time_part else label


def _render_month_rows(items: list[dict], include_detail_link: bool = True, *,
                       trip_names: dict[str, str] | None = None,
                       year: int | None = None, month: int | None = None) -> str:
    from app.assignment_status import row_assignment
    from app.quarter_tab import parse_tab

    rows: list[str] = []
    for date_key, entries in _group_by_date(items):
        rows.append(
            f"<tr class='date-group'><th scope='colgroup' colspan='4'>"
            f"{_esc(_period_date(date_key, year, month) or date_key)} · {len(entries)}건</th></tr>")
        for date_part, time_part, item in entries:
            tid = str(item.get("transaction_id") or "")
            approved = item.get("use_date") or item.get("approval_date")
            date_text = _period_date(approved, year, month)
            if not date_text:
                date_text = "날짜 확인 필요"
            merchant = str(item.get("merchant") or "").strip() or "가맹점 미상"
            card_label = item.get('card_label') or '식별 정보 없음'
            amount = _format_amount(item.get("amount_krw"),
                                    item.get("foreign_amount"),
                                    item.get("foreign_currency"))
            assignment = row_assignment(item, (trip_names or {}).keys())
            # Legacy callers without trip metadata historically displayed stored IDs.
            # Keep that readable fallback; production card pages pass validated names.
            if trip_names is None and assignment['destination'] and not parse_tab(assignment['destination']):
                assignment['status'] = 'ASSIGNED'
            trip_id = assignment['destination']
            quarter = parse_tab(trip_id)
            if assignment['status'] != 'ASSIGNED' or (not quarter and item.get('trip_assignment_valid') is False):
                trip_id = ''
            quarter = parse_tab(trip_id)
            trip_name = (f"{quarter[0]}년 {quarter[1]}분기 기타비용" if quarter
                         else (trip_names or {}).get(trip_id, trip_id))
            source = str(item.get("classification_source") or "").strip()
            if item.get('refund_tab_member'):
                trip_markup = "<a class='card-all-link' href='/board?tab=refunds'>취소·환불</a>"
            elif not trip_id:
                trip_markup = "<span class='card-all-trip-name unassigned'>미배정</span>"
            else:
                trip_markup = (f"<span class='card-all-trip-name' title='{_esc(trip_id)}'>"
                               f"{_esc(trip_name)}</span>")
                if source in ("manual", "auto_inferred"):
                    label = "사용자 확정" if source == "manual" else "추정 배정"
                    trip_markup += f"<span class='card-all-trip-source'>{label}</span>"
            detail_id = 'card-detail-' + tid
            merchant_markup = f"<span class='merchant-name'>{_esc(merchant)}</span>"
            row_attrs = f" data-detail-id='{_esc(tid)}'" if tid and include_detail_link else ''
            if row_attrs:
                merchant_markup = (f"<button type='button' class='card-all-row-toggle' aria-expanded='false' "
                                   f"aria-controls='{_esc(detail_id)}' aria-label='{_esc(merchant)} 상세 보기'>"
                                   f"{merchant_markup}</button>")
            status = _status_badges(item)
            status_markup = f"<div class='card-all-badges'>{status}</div>" if status else ""
            if not trip_id and not status and not item.get('refund_tab_member'):
                trip_markup += _review_action(item)
            rows.append(
                f"<tr role='row' data-tx-id='{_esc(tid)}'{row_attrs}>"
                f"<td role='cell' class='use-datetime' title='{_esc(_format_use_date(approved))}'>{_esc(date_text)}</td>"
                f"<td role='cell' class='merchant' title='{_esc(merchant)}'>{merchant_markup}"
                f"<span class='card-identity' aria-label='카드 식별'>{_esc(card_label)}</span></td>"
                f"<td role='cell' class='amount-cell'><div class='amount'>{_esc(amount)}</div>{status_markup}</td>"
                f"<td role='cell' class='trip' title='{_esc(trip_name)}'>{trip_markup}</td>"
                f"</tr>")
            if row_attrs:
                rows.append(f"<tr class='card-all-expanded' id='{_esc(detail_id)}' hidden>"
                            "<td colspan='4'><div class='card-all-expanded-content' aria-live='polite'></div></td></tr>")
    return "".join(rows)


def _transactions_table(items: list[dict], label: str, *,
                        trip_names: dict[str, str] | None = None,
                        year: int | None = None, month: int | None = None) -> str:
    return (
        "<div class='card-all-table-wrap'>"
        f"<table role='table' class='card-all-table' aria-label='{_esc(label)}'>"
        "<caption class='sr'>저장된 카드 거래 내역</caption>"
        "<colgroup><col class='date-column'><col class='merchant-column'><col class='amount-column'><col class='trip-column'></colgroup>"
        "<thead><tr>"
        "<th scope='col'>이용일시</th>"
        "<th scope='col'>가맹점명</th>"
        "<th scope='col' class='amount'>금액</th>"
        "<th scope='col'>배정</th>"
        "</tr></thead>"
        f"<tbody>{_render_month_rows(items, trip_names=trip_names, year=year, month=month)}</tbody>"
        "</table></div>")


def _undated_section(year: int, items: list[dict], count: int, *,
                     expanded: bool, cursor: str | None, has_more: bool,
                     trip_names: dict[str, str] | None = None, filter_state=None) -> str:
    heading = f"<h2>날짜 확인 필요 · {count:,}건</h2>"
    note = "<p class='card-all-muted'>이용일이 없는 거래는 연도와 관계없이 표시합니다.</p>"
    if count == 0:
        return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
                f"<div id='undated-heading'>{heading}</div>"
                "<p class='card-all-muted'>날짜 확인이 필요한 거래가 없어.</p>"
                "</section>")
    if not expanded:
        href = "/cards/all?" + urlencode({**(filter_state or {}), "year": year, "undated": "1"})
        return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
                f"<div id='undated-heading'>{heading}</div>{note}"
                f"<a class='card-all-link' href='{_esc(href)}'>날짜 확인 필요 목록 보기</a>"
                "</section>")
    more = ""
    if has_more and cursor:
        href = "/cards/all?" + urlencode({**(filter_state or {}), "year": year, "undated": "1",
                                         "undated_cursor": cursor})
        more = ("<div class='card-all-pagination'>"
                f"<a class='card-all-link' href='{_esc(href)}'>다음 날짜 확인 필요 거래 100건 보기</a>"
                "</div>")
    return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
            f"<div id='undated-heading'>{heading}</div>{note}"
            f"{_transactions_table(items, '날짜 확인 필요 거래', trip_names=trip_names)}{more}"
            "</section>")


def _month_detail(year: int, month: int, items: list[dict], cursor, has_more: bool,
                  total: int, *, trip_names: dict[str, str] | None = None, filter_state=None) -> str:
    count_label = '미배정' if (filter_state or {}).get('unassigned') else '전체'
    if not items:
        if total:
            start = "/cards/all?" + urlencode({**(filter_state or {}), "year": year, "month": month})
            return ("<section class='card-all-detail'>"
                    f"<h2>{year}년 {month}월 · {count_label} {total:,}건</h2>"
                    "<p class='card-all-muted'>이 위치에는 표시할 거래가 더 없어. "
                    f"<a class='card-all-link' href='{_esc(start)}'>처음부터 보기</a></p>"
                    "</section>")
        return ("<section class='card-all-detail card-all-empty'>"
                f"<h2>{year}년 {month}월</h2>"
                + ("<p>이 달에 조회 조건에 맞는 카드 거래가 없어.</p>" if filter_state else
                   "<p>이 달에 저장된 카드 거래가 없어.</p>")
                + "</section>")
    more = ""
    if has_more and cursor:
        href = "/cards/all?" + urlencode({**(filter_state or {}), "year": year, "month": month,
                                         "cursor": cursor})
        more = (f"<div class='card-all-pagination'>"
                f"<a class='card-all-link' href='{_esc(href)}'>다음 100건 더 보기</a>"
                "</div>")
    return (f"<section class='card-all-detail' aria-labelledby='month-heading'>"
            f"<h2 id='month-heading'>{year}년 {month}월 · {count_label} {total:,}건</h2>"
            f"{_transactions_table(items, f'{year}년 {month}월 거래', trip_names=trip_names, year=year, month=month)}"
            f"{more}</section>")


def _search_detail(year: int, items: list[dict], cursor, has_more: bool,
                   total: int, *, trip_names: dict[str, str] | None = None,
                   filter_state=None) -> str:
    """Always render a search state, including zero matches."""
    query = str((filter_state or {}).get('q') or '')
    heading = f'검색 결과 · {total:,}건' if query else f'{year}년 전체 · {total:,}건'
    if not items:
        message = f'‘{_esc(query)}’ 검색 결과가 없습니다.' if query else '조회 조건에 맞는 카드 거래가 없습니다.'
        return ("<section class='card-all-detail card-all-search-result' "
                "aria-live='polite' aria-labelledby='search-heading'>"
                f"<h2 id='search-heading'>{heading}</h2>"
                f"<p class='card-all-muted'>{message}</p>"
                "</section>")
    more = ""
    if has_more and cursor:
        href = "/cards/all?" + urlencode({**(filter_state or {}), "year": year,
                                           "cursor": cursor})
        more = ("<div class='card-all-pagination'>"
                f"<a class='card-all-link' href='{_esc(href)}'>다음 검색 결과 100건 보기</a>"
                "</div>")
    return ("<section class='card-all-detail card-all-search-result' "
            "aria-live='polite' aria-labelledby='search-heading'>"
            f"<h2 id='search-heading'>{heading}</h2>"
            f"{_transactions_table(items, '카드 검색 결과', trip_names=trip_names, year=year)}{more}"
            "</section>")


def _period_select(year: int, month: int | None, years: list[int]) -> str:
    selected = f'{year}-{month:02d}' if month else str(year)
    groups = []
    for value in sorted(set(years) | {year}, reverse=True):
        periods = [(str(value), f'{value}년 전체')]
        periods.extend((f'{value}-{m:02d}', f'{value}년 {m}월') for m in range(1, 13))
        options = ''.join(f"<option value='{key}'{' selected' if key == selected else ''}>{label}</option>"
                          for key, label in periods)
        groups.append(f"<optgroup label='{value}년'>{options}</optgroup>")
    return ("<label>기간 <select name='period' aria-label='조회 기간' onchange='this.form.requestSubmit()'>"
            + ''.join(groups) + '</select></label>')


def _available_years(db_path: str | None) -> list[int]:
    result = _ct.available_years(db_path=db_path)
    years = {int(value) for value in result.get("years", []) if str(value).isdigit()}
    years.add(DEFAULT_YEAR)
    return sorted(years, reverse=True)


def _default_db_path():
    from .ledger_board import _get_card_db_path as _board_card_db_path
    return _board_card_db_path()


def _error_page(message: str) -> str:
    body = ("<section class='card-all-empty' role='alert'>"
            "<h2>카드를 불러오지 못했어요</h2>"
            f"<p>{_esc(message)}</p></section>")
    fragment = _design.shell("카드 전체 내역", tab_id="", heading="카드 전체 내역",
                             meta="저장된 카드 거래를 연도와 월로 확인해요.",
                             body=body, home=True)
    return _design.render(fragment, title="카드 전체 내역")


def cards_all_page(query_params: dict, *, db_path: str | None = None) -> str:
    operation = 'card_search' if _first(query_params, 'q', '') else 'first_render'
    with request_metrics.card_scope(operation):
        return _cards_all_page(query_params, db_path=db_path)


def _cards_all_page(query_params: dict, *, db_path: str | None = None) -> str:
    """카드 전체 내역 페이지를 그린다. 읽기만 수행한다."""
    year, selected_month, cursor, undated_cursor, show_undated = _request_params(query_params)
    filter_state = _filter_state(query_params)
    trip_names = {}
    card_db_path = db_path or _default_db_path()
    if not card_db_path:
        return _error_page("카드 원본 DB가 연결되지 않았어요. 운영 설정을 확인해 주세요.")
    try:
        trip_names, valid_trip_ids = _trip_context() if filter_state.get('unassigned') else ({}, set())
        filters = {'unassigned': filter_state.get('unassigned') == '1', 'valid_trip_ids': valid_trip_ids,
                   'card': filter_state.get('card', ''), 'search': filter_state.get('q', '')}
        years = _available_years(card_db_path)
        summary = _ct.year_summary(db_path=card_db_path, year=year, **filters)
        card_options = _ct.card_options(db_path=card_db_path)
        months = summary.get("months") or {}

        items: list[dict] = []
        next_cursor = None
        has_more = False
        month_total = 0
        search_items: list[dict] = []
        search_next_cursor = None
        search_has_more = False
        search_total = 0
        if selected_month is not None:
            try:
                month_total = int(months.get(selected_month, 0) or 0)
            except (TypeError, ValueError):
                month_total = 0
            result = _ct.list_for_month(db_path=card_db_path, year=year,
                                        month=selected_month, cursor=cursor,
                                        per_page=PAGE_SIZE, **filters)
            items = result.get("items") or []
            next_cursor = result.get("cursor")
            has_more = bool(result.get("has_more"))
        elif not show_undated:
            result = _ct.search_for_year(db_path=card_db_path, year=year,
                                         cursor=cursor, per_page=PAGE_SIZE, **filters)
            search_items = result.get("items") or []
            search_next_cursor = result.get("cursor")
            search_has_more = bool(result.get("has_more"))
            search_total = int(result.get("total_count", result.get("count", 0)) or 0)

        undated_count = int(summary.get("undated_count", 0) or 0)
        undated_items: list[dict] = []
        undated_has_more = False
        undated_next_cursor = None
        if show_undated:
            undated_result = _ct.undated_list(
                db_path=card_db_path, year=year, cursor=undated_cursor,
                per_page=UNDATED_PAGE_SIZE, **filters)
            # 날짜 유효성의 권위는 API에 둔다. 무효한 달력 날짜도 API가
            # 날짜 확인 필요 목록으로 돌려줬다면 화면에서 제외하지 않는다.
            undated_items = undated_result.get("items") or []
            # 실제 미확인 건수는 날짜 미확인 API의 total만 신뢰한다.
            # 기존 API는 total을 제공하지 않으므로 페이지 행 수를 전체로 가장하지 않는다.
            if "total_count" in undated_result or "total" in undated_result:
                undated_count = int(undated_result.get("total_count", undated_result.get("total", 0)) or 0)
            undated_has_more = bool(undated_result.get("has_more"))
            undated_next_cursor = undated_result.get("cursor")
    except RuntimeError:
        return _error_page("카드 원본 DB 경로를 확인할 수 없어요.")
    except sqlite3.OperationalError:
        return _error_page("카드 원본 DB에서 거래 표를 읽을 수 없어요.")
    except (ValueError, TypeError):
        return _error_page("조회 조건을 확인하지 못했어요.")

    with request_metrics.card_phase('trip_labels'):
        # Only an already-authorized owner page resolves ledger display labels.
        # This never changes the stored trip_id, the card's classification, or access policy.
        try:
            from . import ledger_board as _board
            if (items or search_items or undated_items) and _board.current_role() == "owner":
                trip_names = {
                    str(t.get("tab_id") or ""): str(t.get("display_key") or t.get("tab_id") or "")
                    for t in _board.live_trips(include_archived=True)
                    if isinstance(t, dict) and t.get("tab_id")
                }
        except (RuntimeError, AttributeError, TypeError):
            pass

    if filters['unassigned']:
        for item in [*items, *search_items, *undated_items]:
            item['trip_assignment_valid'] = False
    with request_metrics.card_phase('card_render'):
        selected_card = filter_state.get('card', '')
        options = "<option value=''>전체 카드</option>" + ''.join(
            f"<option value='{_esc(option['card_key'])}'{' selected' if option['card_key'] == selected_card else ''}>{_esc(option['card_label'])}</option>"
            for option in card_options)
        filter_form = (
            "<form method='get' action='/cards/all' class='card-all-filters'>"
            + _hidden_filters({'undated': '1'} if show_undated else {})
            + _period_select(year, selected_month, years)
            + f"<label class='card-all-unassigned'><input type='checkbox' name='unassigned' value='1'{' checked' if filters['unassigned'] else ''}> 미배정만</label>"
            + f"<label>카드 <select name='card' aria-label='카드별 조회'>{options}</select></label>"
            + f"<label>검색 <input type='search' name='q' value='{_esc(filter_state.get('q', ''))}' placeholder='가맹점·내용·분류·금액·승인번호'></label>"
            + f"<button class='btn' type='submit'>{ui_icons.icon('search')}조회</button>"
            + f"<a class='card-all-link' href='/cards/all?{_esc(urlencode({'year': year, **({'month': selected_month} if selected_month else {})}))}'>필터 초기화</a></form>"
            + "<details class='card-all-help'><summary>조회·상태 안내</summary><p class='card-all-muted'>미배정은 배정된 여행이 없거나 여행 일정 확인이 필요한 거래입니다. 전액 상쇄된 취소·환불 묶음은 취소·환불 탭에 표시합니다. 행을 누르면 해당 거래 상세로 이동합니다. 같은 카드사·종류·끝자리의 카드는 저장된 정보만으로 구분할 수 없습니다.</p></details>")

        if selected_month is not None:
            detail = _month_detail(year, selected_month, items, next_cursor,
                                   has_more, month_total, trip_names=trip_names, filter_state=filter_state)
        elif not show_undated:
            detail = _search_detail(year, search_items, search_next_cursor,
                                    search_has_more, search_total,
                                    trip_names=trip_names, filter_state=filter_state)
        else:
            detail = ''

        body = (
            CARD_ALL_STYLE
            + "<div class='card-all-page'>"
            "<div class='card-all-page-loading' role='status' hidden>"
            "<span class='card-all-spinner' aria-hidden='true'></span>불러오는 중</div>"
            "<header class='card-all-hero'>"
            "<div><p class='card-all-eyebrow'>CARD TRANSACTION HISTORY</p>"
            "<p class='card-all-lead'>월별 카드 거래 확인</p>"
            "</div>"
            "<div class='card-all-summary' aria-label='저장 거래 요약'>"
            f"<div class='card-all-stat'><span class='card-all-stat-label'>{year}년 날짜 확인 거래</span><strong class='card-all-stat-value'>{sum(int(v or 0) for v in months.values()):,}건</strong></div>"
            f"<div class='card-all-stat'><span class='card-all-stat-label'>날짜 확인 필요</span><strong class='card-all-stat-value'>{undated_count:,}건</strong></div>"
            "</div></header>"
            "<div class='card-all-toolbar'><h2 class='card-all-toolbar-title'>조회 조건</h2></div>"
            f"{filter_form}"
            f"{detail}"
            f"{_undated_section(year, undated_items, undated_count, expanded=show_undated, cursor=undated_next_cursor, has_more=undated_has_more, trip_names=trip_names, filter_state=filter_state)}"
            "</div>" + CARD_ALL_SCRIPT)
        fragment = _design.shell(
            "카드 전체 내역", tab_id="", heading="카드 전체 내역",
            meta="카드 거래를 연도와 월로 확인해요.",
            body=body, home=True)
        return _design.render(fragment, title="카드 전체 내역")
