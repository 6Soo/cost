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
from . import ui_components
from .card_history_assets import SCRIPT as CARD_HISTORY_WORKSPACE_SCRIPT
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
.card-all-page{--ca-border:var(--line,var(--c-border));--ca-muted:var(--mut,var(--c-text-tertiary));--ca-ink:var(--ink,var(--c-text));--ca-paper:var(--paper,var(--c-surface));--ca-soft:var(--hover,var(--c-surface-sunken));--ca-accent:var(--shell-accent,var(--grn,var(--c-accent-solid)));color:var(--ca-ink);max-width:1260px;margin:0 auto;padding:24px 24px 64px;font:inherit}
.card-all-page *{box-sizing:border-box}
.card-all-page .card-all-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;padding:22px 24px;border:1px solid var(--ca-border);border-radius:var(--r-lg);background:var(--ca-paper);margin-bottom:18px}
.card-all-page .card-all-eyebrow{font-size:var(--t-caption);font-weight:750;letter-spacing:.045em;color:var(--ca-accent);margin:0 0 5px}
.card-all-page .card-all-lead{font-size:var(--t-body-sm);font-weight:700;margin:0}
.card-all-page .card-all-description{font-size:var(--t-caption);color:var(--ca-muted);margin:5px 0 0;max-width:52ch;line-height:1.55}
.card-all-page .card-all-summary{display:grid;grid-template-columns:repeat(2,minmax(110px,1fr));gap:10px}
.card-all-page .card-all-stat{display:grid;gap:3px;min-width:115px;padding:12px 15px;border:1px solid var(--ca-border);background:var(--ca-soft);border-radius:var(--r-md)}
.card-all-page .card-all-stat-label{font-size:var(--t-caption);color:var(--ca-muted);font-weight:650}
.card-all-page .card-all-stat-value{font-size:var(--t-h3);font-variant-numeric:tabular-nums;font-weight:800}
.card-all-page .card-all-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 12px;flex-wrap:wrap}
.card-all-page .card-all-toolbar-title{font-size:var(--t-body);font-weight:750;margin:0}











.card-all-page :is(button,a,select):focus-visible{outline:2px solid var(--focus,var(--c-focus));outline-offset:3px}
.card-all-page :is(.card-all-detail,.card-all-undated,.card-all-prompt){border:1px solid var(--ca-border);border-radius:var(--r-lg);background:var(--ca-paper);padding:19px 20px;margin:0 0 16px}
.card-all-page :is(.card-all-detail,.card-all-undated) h2{margin:0 0 14px;font-size:var(--t-body);font-weight:750;line-height:1.5}
.card-all-page .card-all-prompt{color:var(--ca-muted);font-size:var(--t-meta)}
.card-all-page .card-all-muted{font-size:var(--t-caption);line-height:1.6;color:var(--ca-muted)}
.card-all-page .card-all-table-wrap{width:100%;min-width:0;border-radius:var(--r-md);border:1px solid var(--ca-border)}
.card-all-page .card-all-table{table-layout:fixed;border-collapse:separate;border-spacing:0;width:100%;min-width:0;background:var(--ca-paper);font-size:var(--t-meta);line-height:1.4}
.card-all-page .card-all-table .date-column{width:17%}
.card-all-page .card-all-table .merchant-column{width:32%}
.card-all-page .card-all-table .amount-column{width:24%}
.card-all-page .card-all-table .trip-column{width:27%}
.card-all-page .card-all-table th,.card-all-page .card-all-table td{padding:7px 6px;text-align:left;vertical-align:middle;border:0;overflow-wrap:anywhere}
.card-all-page .card-all-table thead th{position:sticky;top:0;background:var(--ca-soft);color:var(--ca-muted);font-size:var(--t-caption);font-weight:700;z-index:1}
.card-all-page .card-all-table .date-group th{padding:9px 14px;background:var(--ca-soft);color:var(--ca-ink);font-size:var(--t-caption);font-weight:750}
@media(hover:hover){.card-all-page .card-all-table tbody tr:not(.date-group):hover{background:var(--ca-soft)}}
.card-all-page .card-all-table tbody tr:last-child td{border-bottom:0}
.card-all-page .card-all-table .amount{text-align:right;font-weight:750;font-variant-numeric:tabular-nums}
.card-all-page .card-all-table .amount-cell .amount{white-space:normal;overflow-wrap:anywhere}
.card-all-page .card-all-table .use-datetime{font-variant-numeric:tabular-nums;white-space:normal;color:var(--ca-muted)}
.card-all-page .card-all-table .merchant{font-weight:700;overflow-wrap:anywhere}
.card-all-page .card-all-table .merchant{min-width:0}
.card-all-page .card-all-table tr[data-detail-id]{cursor:pointer}
.card-all-page .card-all-table tr[data-detail-id]:focus-within{outline:2px solid var(--focus,var(--c-focus));outline-offset:-2px;background:var(--ca-soft)}
 .card-all-page .card-all-row-toggle{display:block;width:100%;height:auto;min-height:44px;margin:0;padding:0;border:0;border-radius:0;appearance:none;-webkit-appearance:none;background:none;color:inherit;text-align:left;font:inherit;line-height:inherit;cursor:pointer;overflow-wrap:anywhere;min-width:0}
 .card-all-page .card-all-row-toggle:focus-visible{outline:2px solid var(--focus,var(--c-focus));outline-offset:2px}
 .card-all-page .card-all-mobile-list{display:none;list-style:none;margin:0;padding:0}
 .card-all-page .card-all-mobile-list .list-row{margin:0;border-bottom:1px solid var(--ca-border);background:var(--ca-paper)}
 .card-all-page .card-all-mobile-list .list-row:last-child{border-bottom:0}
 .card-all-page .card-all-mobile-list .lr-hit{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"primary amount" "secondary secondary";align-items:baseline;width:100%;min-height:56px;gap:3px 12px;padding:10px 12px;border:0;background:transparent;color:inherit;text-align:left;font:inherit;cursor:pointer}
 .card-all-page .card-all-mobile-list .lr-primary{grid-area:primary;font-weight:700;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
 .card-all-page .card-all-mobile-list .lr-amount{grid-area:amount;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
 .card-all-page .card-all-mobile-list .lr-secondary{grid-area:secondary;color:var(--ca-muted);font-size:var(--t-caption);overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:1;overflow:hidden}
 .card-all-page .card-all-mobile-expanded{padding:0 12px 12px;background:var(--ca-soft)}
 .card-all-page .card-all-mobile-expanded[hidden]{display:none}
.card-all-page .card-all-expanded td{padding:12px;background:var(--ca-soft)}
.card-all-page .card-all-expanded[hidden]{display:none}
.card-all-page .card-all-expanded-content{min-width:0;overflow-wrap:anywhere}
.card-all-page .card-all-action{margin:0 0 14px;padding:12px 14px;border-left:3px solid var(--ca-accent);background:var(--ca-paper);line-height:1.55}
.card-all-page .card-all-action p{margin:4px 0}
.card-all-page .card-all-action .card-all-link{font-size:var(--t-meta);min-height:36px;align-items:center}
.card-detail-fields{display:grid;grid-template-columns:minmax(60px,auto) minmax(0,1fr);gap:8px 12px;margin:0;font-size:var(--t-caption);line-height:1.5}
.card-detail-fields dt{color:var(--mut,var(--c-text-tertiary))}
.card-detail-fields dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;min-width:0}
.card-all-page .card-all-loading{display:flex;align-items:center;gap:8px;font-size:var(--t-caption);color:var(--ca-muted)}
.card-all-spinner{display:inline-block;width:18px;height:18px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:card-all-spin .7s linear infinite;flex-shrink:0}
@keyframes card-all-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.card-all-spinner{animation-duration:1.8s}}
.card-all-page .card-all-page-loading{position:fixed;inset:0;z-index:1000;background:var(--ca-paper);opacity:.94;display:flex;align-items:center;justify-content:center;gap:10px}
.card-all-page .card-all-page-loading[hidden]{display:none}
.card-all-page .card-identity{display:block;font-size:var(--t-caption);line-height:1.5;font-weight:500;color:var(--ca-muted);margin-top:4px}
.card-all-page .card-all-table .amount-cell{text-align:right}
.card-all-page .card-all-table .amount-cell .amount{text-align:right;font-weight:750;font-variant-numeric:tabular-nums}
.card-all-page .card-all-table .amount-cell .card-all-badges{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:3px}
.card-all-page .filter-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 16px;font-size:var(--t-meta)}
.card-all-page .filter-bar>label{display:inline-flex;align-items:center;gap:7px;min-width:0}
.card-all-page .filter-bar :is(input[type=search],select){min-height:42px;max-width:100%;padding:8px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper);color:var(--ca-ink);font:inherit}
.card-all-page .filter-bar input[type=search]{width:min(360px,100%)}
.card-all-page .filter-bar button{min-height:42px;padding:8px 14px;font:inherit}
.card-all-page .card-all-table .trip{min-width:0;overflow-wrap:anywhere}
.card-all-page .card-all-trip-name{display:block;font-weight:700;line-height:1.4}
.card-all-page .card-all-trip-name.unassigned{color:var(--ca-muted);font-weight:500}
.card-all-page .card-all-trip-source{display:inline-flex;margin-top:4px;font-size:var(--t-caption);line-height:1.5;color:var(--ca-muted)}
.card-all-page .card-all-badge{display:inline-flex;margin:5px 0 0;padding:2px 7px;border-radius:var(--r-sm);border:1px solid var(--ca-border);background:var(--ca-soft);font-size:var(--t-caption);color:var(--ca-ink)}
.card-all-page .card-all-link{color:var(--ca-accent);font-weight:750;font-size:var(--t-caption);text-decoration:underline;text-underline-offset:3px}
.card-all-page .card-all-table .card-all-link{display:inline-flex;white-space:normal;overflow-wrap:anywhere;margin-top:6px}
.card-all-page .card-all-pagination{margin-top:15px;display:flex;justify-content:center}
.card-all-page .card-all-pagination a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:10px 16px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-soft);text-decoration:none}
.card-all-page .card-all-help{margin:0 0 16px;font-size:var(--t-caption);color:var(--ca-muted)}
.card-all-page .card-all-help summary{cursor:pointer;min-height:44px;align-content:center;width:fit-content}
.card-all-page .card-all-help p{margin:0 0 12px;max-width:80ch}
/* Compact, flat card-history layout: one content plane with clear row separators. */
.card-all-page{padding:14px 18px 40px}
.card-all-page .card-all-hero{border:0;border-radius:0;background:transparent;padding:0 0 12px;margin:0 0 12px;border-bottom:1px solid var(--ca-border);gap:12px}
.card-all-page .card-all-eyebrow{display:none}
.card-all-page .card-all-lead{font-size:var(--t-body-sm)}
.card-all-page .card-all-summary{display:flex;gap:18px;align-items:baseline}
.card-all-page .card-all-stat{display:flex;gap:7px;align-items:baseline;min-width:0;padding:0;border:0;border-radius:0;background:transparent}
.card-all-page .card-all-stat-value{font-size:var(--t-body-sm)}
.card-all-page .card-all-toolbar{display:none}
.card-all-page .filter-bar{margin:0 0 8px;gap:8px;padding:0;border:0;background:transparent}
.card-all-page .filter-bar :is(input[type=search],select){min-height:42px;padding:6px 9px}
.card-all-page .filter-bar button{min-height:44px}
.card-all-page .card-all-help{margin:0 0 10px}
.card-all-page .card-all-help summary{min-height:44px}
.card-all-page :is(.card-all-detail,.card-all-undated){border:0;border-radius:0;background:transparent;padding:0;margin:0 0 20px}
.card-all-page :is(.card-all-detail,.card-all-undated) h2{font-size:var(--t-body);margin:8px 0 10px}
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
 .card-all-page .card-all-lead{font-size:var(--t-meta)}
 .card-all-page .card-all-summary{width:auto;display:flex;gap:10px;flex-wrap:wrap}
 .card-all-page .card-all-stat{display:flex;gap:4px;padding:0}
 .card-all-page .card-all-stat-label{font-size:var(--t-caption)}
 .card-all-page .card-all-stat-value{font-size:var(--t-caption)}
 .card-all-page .filter-bar{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;padding:0;border:0;border-radius:0;background:transparent;margin:0 0 5px}
 .card-all-page .filter-bar>label{grid-column:auto;display:flex;flex-direction:column;align-items:stretch;gap:3px;font-size:var(--t-caption)}
 .card-all-page .filter-bar>label:has(input[type=search]){grid-column:1/-1}
 .card-all-page .filter-bar>label:has(select[name=period]){grid-column:1;grid-row:1}
 .card-all-page .filter-bar>label:has(select[name=card]){grid-column:2;grid-row:1}


 .card-all-page .filter-bar input[type=checkbox]{width:20px;height:20px;accent-color:var(--ca-accent);flex-shrink:0}
 .card-all-page .filter-bar :is(input[type=search],select){min-height:44px;font-size:var(--t-body);padding:5px 8px}
 .card-all-page .filter-bar button,.card-all-page .filter-bar>.card-all-link{grid-column:auto;width:100%;min-height:44px;padding:5px 8px}
 .card-all-page .filter-bar>.card-all-link{display:flex;align-items:center;justify-content:center}
 .card-all-page .card-all-help{padding:0;margin:0 0 8px}
 .card-all-page .card-all-detail,.card-all-page .card-all-undated{padding:0;margin:0 0 14px}
 .card-all-page :is(.card-all-detail,.card-all-undated) h2{font-size:var(--t-body-sm);margin:6px 0 8px}
 .card-all-page .card-all-table-wrap{border:0;border-radius:0}
 .card-all-page .card-all-table{font-size:var(--t-caption)}
 .card-all-page .card-all-table th,.card-all-page .card-all-table td{padding:8px 4px}
 .card-all-page .card-all-table .date-column{width:14%}
 .card-all-page .card-all-table .merchant-column{width:36%}
 .card-all-page .card-all-table .amount-column{width:25%}
 .card-all-page .card-all-table .trip-column{width:25%}
 .card-all-page .card-all-table .merchant-name{font-size:var(--t-caption);line-height:1.35}
 .card-all-page .card-identity{font-size:var(--t-caption);margin-top:2px}
 .card-all-page .card-all-table .amount{font-size:var(--t-caption)}
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
 .card-all-page .card-all-table tbody tr.date-group th{display:block;padding:7px 2px 5px;border:0;background:transparent;font-size:var(--t-caption);font-weight:700;color:var(--ca-muted);text-align:left}
 .card-all-page .card-all-table tbody tr[data-tx-id]{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,46%);grid-template-areas:"merchant amount" "merchant trip";column-gap:12px;align-items:start;width:100%;min-height:44px;padding:4px 2px;border-bottom:1px solid var(--ca-border)}
 .card-all-page .card-all-table tbody tr[data-tx-id]>td{display:block;padding:0;border:0;min-width:0;vertical-align:initial}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.use-datetime{display:none}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.merchant{grid-area:merchant;font-size:var(--t-meta);font-weight:700;line-height:1.35;overflow-wrap:anywhere}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.amount-cell{grid-area:amount;text-align:right;align-self:start}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.trip{grid-area:trip;align-self:end;text-align:right;font-size:var(--t-caption);max-width:145px}
 .card-all-page .card-all-table .card-all-row-toggle{min-height:44px}
 .card-all-page .card-all-table .merchant-name{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:1;overflow:hidden}
 .card-all-page .card-all-table .card-identity{display:block;margin-top:5px;font-size:var(--t-caption);line-height:1.3;font-weight:400}
 .card-all-page .card-all-table .amount-cell .amount{font-size:var(--t-body-sm);font-weight:750;white-space:normal;overflow-wrap:anywhere}
 .card-all-page .card-all-table .card-all-trip-name{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--t-caption);line-height:1.35;font-weight:600}
 .card-all-page .card-all-table .card-all-trip-source{display:none}
 .card-all-page .card-all-table .card-all-badges{max-width:135px}
 .card-all-page .card-all-table .card-all-action-reason{display:none}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.amount-cell{display:flex;align-items:center;justify-content:flex-end;gap:4px}
 .card-all-page .card-all-table tbody tr[data-tx-id]>.amount-cell>.amount{flex:1 1 auto;min-width:0}
 .card-all-page .card-all-table .amount-cell .card-all-badges{display:flex;flex:0 1 auto;max-width:88px;margin:0}
 .card-all-page .card-all-table .card-all-badge{margin:0}
 .card-all-page .card-all-table a.card-all-badge.card-review-action{min-width:44px;min-height:44px;align-items:center;justify-content:center}
 .card-all-page .card-all-table tbody tr.card-all-expanded:not([hidden]){display:block;width:100%;border-bottom:1px solid var(--ca-border)}
 .card-all-page .card-all-table tbody tr.card-all-expanded>td{display:block;width:100%;padding:10px 4px}
 .card-all-page .card-all-table tbody tr.card-all-expanded[hidden]{display:none}
}

.card-all-page .card-history-workspace{margin:0 0 14px;min-width:0}
.card-all-page .card-history-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin:0 0 10px}
.card-all-page .card-history-actions button{min-height:44px;padding:8px 14px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper);color:var(--ca-ink);font:inherit;font-weight:700;cursor:pointer}
.card-all-page .card-history-actions #card-upload-open{background:var(--ca-accent);border-color:var(--ca-accent);color:var(--c-on-accent)}
.card-all-page .card-history-actions button[aria-expanded=true]{outline:2px solid var(--focus,var(--c-focus));outline-offset:2px}
.card-all-page .card-history-actions button:focus-visible,.card-all-page .card-workspace-panel :is(button,a,input,select,summary):focus-visible{outline:2px solid var(--focus,var(--c-focus));outline-offset:3px}
.card-all-page .card-workspace-panel{min-width:0;margin:10px 0 16px;padding:16px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper)}
.card-all-page .card-workspace-panel[hidden]{display:none}
.card-all-page .card-workspace-panel>header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}
.card-all-page .card-workspace-panel-actions{display:flex;align-items:flex-start;gap:8px;flex:0 0 auto}
.card-all-page .card-workspace-panel h2,.card-all-page .card-workspace-panel h3{margin:0 0 8px;line-height:1.3}
.card-all-page .card-workspace-panel h2{font-size:var(--t-h3)}
.card-all-page .card-workspace-panel h3{font-size:var(--t-body-sm)}
.card-all-page .card-workspace-panel p{line-height:1.5}
.card-all-page .card-workspace-panel :is(button,a){min-height:44px}
.card-all-page .card-workspace-panel :is(input[type=file],input[type=date],select){min-height:44px;max-width:100%;font:inherit}
.card-all-page .card-workspace-muted{color:var(--ca-muted);font-size:var(--t-meta);overflow-wrap:anywhere}
.card-all-page .card-workspace-status{min-height:1.5em;margin:8px 0;color:var(--ca-ink);font-size:var(--t-meta)}
.card-all-page .card-workspace-error{padding:12px;border-inline-start:3px solid var(--warn,var(--c-warn-text));background:var(--ca-soft);overflow-wrap:anywhere}
.card-all-page .card-workspace-secondary,.card-all-page .card-upload-result-link{display:inline-flex;align-items:center;justify-content:center;padding:8px 12px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper);color:var(--ca-ink);font:inherit;font-weight:650;text-decoration:none;cursor:pointer}
.card-all-page .card-upload-form{display:grid;gap:8px;max-width:760px}
.card-all-page .card-upload-form label{font-weight:650}
.card-all-page .card-upload-form input[type=file]{display:block;width:100%;padding:8px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper);color:var(--ca-ink)}
.card-all-page .card-upload-results{display:grid;gap:8px;margin:12px 0 0;padding:0;list-style:none}
.card-all-page .card-upload-results[hidden]{display:none}
.card-all-page .card-upload-result{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:8px 14px;align-items:start;padding:10px 0;border-bottom:1px solid var(--ca-border);min-width:0}
.card-all-page .card-upload-result-name{overflow-wrap:anywhere}
.card-all-page .card-upload-result-state,.card-all-page .card-upload-result-note{color:var(--ca-muted);font-size:var(--t-meta);overflow-wrap:anywhere}
.card-all-page .card-upload-result-link,.card-all-page .card-upload-coverage-confirm{grid-column:1/-1;width:fit-content;max-width:100%}
.card-all-page .card-upload-coverage-form,.card-all-page .card-coverage-baseline-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 12px;margin:10px 0}
.card-all-page .card-upload-coverage-form>label,.card-all-page .card-coverage-baseline-form>label{display:grid;gap:4px;min-width:0;font-size:var(--t-meta)}
.card-all-page .card-upload-coverage-form .card-upload-coverage-check{grid-column:1/-1;display:flex;align-items:flex-start;gap:8px}
.card-all-page .card-upload-coverage-form .card-workspace-status,.card-all-page .card-upload-coverage-form button,.card-all-page .card-coverage-baseline-form button{grid-column:1/-1}
.card-all-page #card-coverage-status.is-quiet{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.card-all-page .card-coverage-cards{display:grid;grid-template-columns:minmax(0,1fr);align-items:start;gap:12px}
.card-all-page .card-coverage-card{min-width:0;margin:0;padding:16px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper)}
.card-all-page .card-coverage-card-heading{display:flex;align-items:center;justify-content:space-between;gap:8px 16px;flex-wrap:wrap;margin-bottom:12px}
.card-all-page .card-coverage-card-heading h3{margin:0;font-size:var(--t-body);overflow-wrap:anywhere}
.card-all-page .card-coverage-state{color:var(--ca-muted);font-size:var(--t-caption);line-height:1.5}
.card-all-page .card-coverage-state.has-gap{padding:3px 8px;border-radius:var(--r-sm);background:var(--ca-soft);color:var(--ca-ink);font-weight:650}
.card-all-page .card-coverage-period{display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:0;overflow-wrap:anywhere}
.card-all-page .card-coverage-period.is-missing{margin:0 0 16px;padding:12px;border:1px solid var(--ca-border);border-inline-start:3px solid var(--shell-warn,var(--warn,var(--c-warn-text)));border-radius:var(--r-sm);background:var(--ca-soft)}
.card-all-page .card-coverage-gap-label{display:grid;gap:4px;min-width:0}
.card-all-page .card-coverage-gap-label .card-coverage-label{color:var(--ca-ink)}
.card-all-page .card-coverage-label{color:var(--ca-muted);font-size:var(--t-caption);line-height:1.5}
.card-all-page .card-coverage-gap-label .card-coverage-date-range{font-size:var(--t-body-sm);font-weight:650;line-height:1.5}
.card-all-page .card-coverage-period button{flex:0 0 auto}
.card-all-page .card-workspace-secondary.card-coverage-add{background:var(--ca-accent);border-color:var(--ca-accent);color:var(--ca-paper);text-decoration:none;font-size:var(--t-body-sm)}
.card-all-page .card-coverage-ranges{display:grid;grid-template-columns:88px minmax(0,1fr);align-items:baseline;gap:8px 12px;font-size:var(--t-meta);line-height:1.5}
.card-all-page details.card-coverage-ranges{display:block}
.card-all-page details.card-coverage-ranges .card-coverage-range-values{margin-top:8px}
.card-all-page .card-coverage-range-values{display:flex;flex-wrap:wrap;gap:6px 20px;min-width:0}
.card-all-page .card-coverage-date-range{max-width:100%;font-variant-numeric:tabular-nums}
.card-all-page .card-coverage-dates{display:inline-block;white-space:nowrap;font-variant-numeric:tabular-nums}
.card-all-page .card-coverage-baseline,.card-all-page .card-coverage-files{margin-top:10px;border-top:1px solid var(--ca-border);padding-top:8px}
.card-all-page .card-coverage-baseline summary,.card-all-page .card-coverage-files summary,.card-all-page .card-upload-coverage-confirm summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-weight:650}
.card-all-page .card-coverage-file{display:flex;align-items:center;justify-content:space-between;gap:8px 16px;min-width:0;padding:12px 0;border-bottom:1px solid var(--ca-border);overflow-wrap:anywhere}
.card-all-page .card-coverage-file-info{flex:1;min-width:0}
.card-all-page .card-coverage-file-info>strong{display:block;font-size:var(--t-meta);font-weight:600;line-height:1.5}
.card-all-page .card-coverage-file p{margin:4px 0}
.card-all-page .card-coverage-empty{padding:14px;border:1px dashed var(--ca-border);border-radius:var(--r-md)}
.card-all-page .card-coverage-pending{margin-top:14px}
.card-all-page .card-coverage-guidance{margin:8px 0 12px;padding:10px 12px;border-inline-start:3px solid var(--ca-accent);background:var(--ca-soft);font-size:var(--t-meta);line-height:1.5;overflow-wrap:anywhere}
.card-all-page .card-coverage-review{margin-top:16px;border-top:1px solid var(--ca-border);padding-top:12px}
.card-all-page .card-coverage-review>h3{margin:0 0 6px;font-size:var(--t-body-sm)}
.card-all-page .card-coverage-review>.card-workspace-muted{margin:0 0 8px}
.card-all-page .card-coverage-review>.card-coverage-files{margin-top:0;padding:0 0 2px}
.card-all-page .card-coverage-file-actions{display:flex;align-items:center;gap:8px;flex:0 0 auto;flex-wrap:wrap}
.card-all-page .card-coverage-file-actions .card-upload-result-link{white-space:normal}
.card-all-page .card-coverage-file-link{display:inline-flex;align-items:center;min-height:44px;font-size:var(--t-meta);text-underline-offset:3px;color:var(--ca-ink)}
.card-all-page .card-coverage-disclosure{margin-top:16px;border-top:1px solid var(--ca-border);padding-top:8px}
.card-all-page .card-coverage-method{margin-top:0;border-top:0;padding-top:0}
.card-all-page #card-coverage-summary summary{display:flex;align-items:center;justify-content:flex-start;gap:8px;min-height:44px;margin:0;padding:8px 4px;border:0;border-radius:var(--r-sm);background:transparent;font-size:var(--t-meta);font-weight:600;line-height:1.5;list-style:none;cursor:pointer}
.card-all-page #card-coverage-summary summary::-webkit-details-marker{display:none}
.card-all-page #card-coverage-summary summary::before{display:none}
.card-all-page #card-coverage-summary summary::after{margin-inline-start:4px}
.card-all-page #card-coverage-summary .card-coverage-method>summary{color:var(--ca-muted);font-weight:400}
.card-all-page .card-coverage-card-heading .card-workspace-muted{margin:4px 0 0}
.card-all-page .card-coverage-source-name{display:block;margin-top:4px;color:var(--ca-muted);font-size:var(--t-meta);font-weight:400;line-height:1.5}

.card-all-page .card-linked-transaction{margin:0 0 12px;padding:12px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper)}
.card-all-page .card-linked-transaction[hidden]{display:none}
.card-all-page .card-linked-transaction-content{min-width:0;overflow-wrap:anywhere}
.card-all-page .card-legacy-notice{margin:0 0 12px;padding:12px;border-inline-start:3px solid var(--ca-accent);background:var(--ca-soft)}
@media(max-width:760px){
 .card-all-page .card-workspace-panel{padding:12px}
 .card-all-page .card-workspace-panel>header{display:block}
 .card-all-page .card-workspace-panel-actions{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;margin-top:8px}
 .card-all-page .card-workspace-panel-actions button{width:100%;white-space:nowrap}
 .card-all-page .card-coverage-cards{grid-template-columns:minmax(0,1fr)}
 .card-all-page .card-history-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
 .card-all-page .card-history-actions button{width:100%;min-width:0}
 .card-all-page .card-upload-result{grid-template-columns:minmax(0,1fr)}
 .card-all-page .card-upload-result-link,.card-all-page .card-upload-coverage-confirm{grid-column:1}
}
@media(max-width:600px){
 .card-all-page #card-coverage-panel .card-workspace-panel-actions{display:flex;justify-content:flex-end;gap:8px}
 .card-all-page #card-coverage-panel .card-workspace-panel-actions button{width:auto}
 .card-all-page .card-coverage-card{padding:12px}
 .card-all-page .card-coverage-ranges{grid-template-columns:minmax(0,1fr);gap:4px}
 .card-all-page .card-coverage-period{align-items:stretch;flex-direction:column}
 .card-all-page .card-coverage-period button{width:100%}
 .card-all-page .card-coverage-file{align-items:flex-start;flex-direction:column;gap:0}
}
@media(max-width:420px){
 .card-all-page .card-history-actions{grid-template-columns:minmax(0,1fr)}
 .card-all-page .card-upload-coverage-form,.card-all-page .card-coverage-baseline-form{grid-template-columns:minmax(0,1fr)}
 .card-all-page .card-coverage-period{align-items:flex-start;flex-direction:column}
 .card-all-page .card-coverage-period button{width:100%}
}

 .card-all-page .ph-actions{justify-content:flex-end}
 .card-all-page .ph-actions .btn{min-height:44px}
 @media (width < 1024px){.card-all-page .ph-actions .btn{min-height:44px}}
 @media (width < 1024px){.card-all-page .card-all-table-wrap{display:none}.card-all-page .card-all-mobile-list{display:block;border:1px solid var(--ca-border);border-radius:var(--r-lg);overflow:hidden;background:var(--ca-paper)}}
 .card-all-page .filter-bar{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;margin:0 0 16px;font-size:var(--t-meta);min-width:0}
 .card-all-page .filter-bar .field{display:flex;align-items:center;gap:7px;min-width:0}
 .card-all-page .filter-bar .field input,.card-all-page .filter-bar .field select{box-sizing:border-box;min-width:0;max-width:100%;min-height:42px;padding:8px;border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper);color:var(--ca-ink);font:inherit}
 .card-all-page .filter-bar .field input[type=search]{width:min(360px,100%)}
 .card-all-page .filter-bar button,.card-all-page .filter-bar>.btn{min-height:42px;padding:8px 14px;font:inherit}
 @media(max-width:759px){
  .card-all-page .filter-bar{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;margin:0 0 8px}
  .card-all-page .filter-bar .field{display:flex;flex-direction:column;align-items:stretch;gap:3px;min-width:0;font-size:var(--t-caption)}
  .card-all-page .filter-bar .field:has(input[type=search]){grid-column:1/-1}
  .card-all-page .filter-bar .field:has(select[name=period]){grid-column:1;grid-row:1}
  .card-all-page .filter-bar .field:has(select[name=card]){grid-column:2;grid-row:1}
  .card-all-page .filter-bar .field input,.card-all-page .filter-bar .field select{width:100%;min-height:44px;font-size:var(--t-body);padding:5px 8px}
  .card-all-page .filter-bar button,.card-all-page .filter-bar>.btn{width:100%;min-height:44px;padding:5px 8px}
  .card-all-page .filter-bar>.btn{display:flex;align-items:center;justify-content:center}
 }
 .card-all-page details>summary{list-style:none}.card-all-page details>summary::-webkit-details-marker{display:none}.card-all-page details>summary::after{content:'';display:inline-block;width:7px;height:7px;margin-inline-start:auto;border-inline-end:1.5px solid currentColor;border-block-end:1.5px solid currentColor;transform:rotate(45deg);transition:transform var(--motion-fast);flex:0 0 7px}.card-all-page details[open]>summary::after{transform:rotate(225deg)}@media(prefers-reduced-motion:reduce){.card-all-page details>summary::after{transition:none}}</style>
"""

CARD_ALL_SCRIPT = """
<script>
document.addEventListener('click', async function(event) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const target = event.target instanceof Element ? event.target : event.target.parentElement;
     const row = target && target.closest('.card-all-table tr[data-detail-id], .card-all-mobile-list li[data-detail-id]');
     if (!row || window.getSelection().toString()) return;
     if (target.closest('a,input,select,textarea,summary') || (target.closest('button') && !target.closest('.card-all-row-toggle,.card-all-mobile-row-toggle'))) return;
     const toggle = row.querySelector('.card-all-row-toggle,.card-all-mobile-row-toggle');
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
     const row = event.target.closest('.card-all-table tr[data-detail-id], .card-all-mobile-list li[data-detail-id]');
     if (!row) return;
     const detail = row.classList.contains('card-all-expanded') ? row :
                    row.querySelector('.card-all-mobile-expanded') || row.nextElementSibling;
     if (!detail || (!detail.classList.contains('card-all-expanded') && !detail.classList.contains('card-all-mobile-expanded')) || detail.hidden) return;
     detail.hidden = true;
     const toggle = row.querySelector('.card-all-row-toggle,.card-all-mobile-row-toggle');
     toggle.setAttribute('aria-expanded', 'false');
    toggle.focus();
});
document.addEventListener('submit', function(event) {
    if (!event.target.matches('.filter-bar')) return;
    document.querySelector('.card-all-page-loading').hidden = false;
});
document.addEventListener('click', function(event) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('.card-all-page a[href]');
    if (link && link.origin === location.origin && !link.target && !link.hasAttribute('download')) {
        const current = new URL(location.href).searchParams;
        const destination = new URL(link.href);
        let changed = false;
        for (const key of ['panel', 'batch', 'transaction', 'gap_card', 'gap_start', 'gap_end',
                           'gap_issuer', 'gap_basis', 'legacy_cleanup', 'legacy_import']) {
            if (current.has(key) && !destination.searchParams.has(key)) {
                destination.searchParams.set(key, current.get(key));
                changed = true;
            }
        }
        if (changed) {
            link.href = destination.pathname + destination.search + destination.hash;
        }
        document.querySelector('.card-all-page-loading').hidden = false;
    }
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
    for name in ('card', 'q'):
        value = str(_first(query_params, name, '') or '').strip()[:200]
        if value:
            state[name] = value
    return state


def _hidden_filters(state):
    return ''.join(f"<input type='hidden' name='{_esc(key)}' value='{_esc(value)}'>"
                   for key, value in (state or {}).items())


def _workspace_html(query_params, *, owner: bool, csrf: str) -> str:
    if not owner:
        return ""
    active = _first(query_params, 'panel', '')
    active = active if active in ('upload', 'coverage') else ''
    batch = str(_first(query_params, 'batch', '') or '')
    transaction = str(_first(query_params, 'transaction', '') or '')
    batch = batch if re.fullmatch(r'batch-[a-f0-9]{24}', batch) else ''
    show_transaction = bool(transaction and len(transaction) <= 200)
    legacy_cleanup = _first(query_params, 'legacy_cleanup') == '1'
    legacy_import = _first(query_params, 'legacy_import') == '1'
    if legacy_cleanup:
        notice = ("<aside class='card-legacy-notice' role='status'>이전 거래 화면을 카드 내역으로 통합했습니다. "
                  "거래와 원본 근거를 이 화면에서 확인할 수 있습니다.</aside>")
    elif legacy_import:
        notice = ("<aside class='card-legacy-notice' role='status'>이전 카드 처리 화면은 카드 내역으로 통합했습니다. "
                  "업로드와 거래일자 공백은 이 화면에서 확인할 수 있습니다.</aside>")
    else:
        notice = ""
    transaction_panel = (
        "<section id='card-linked-transaction' class='card-linked-transaction' tabindex='-1' hidden>"
        "<h2>연결된 카드 거래</h2><p class='card-workspace-status' role='status' aria-live='polite'></p>"
        "</section>" if show_transaction else "")
    return (
        "<section class='card-history-workspace' data-card-history-workspace data-csrf='" + _esc(csrf) + "'>"
        + notice + transaction_panel +
        f"<section id='card-upload-panel' class='card-workspace-panel' aria-labelledby='card-upload-heading' tabindex='-1'{'' if active == 'upload' else ' hidden'}>"
        "<header><div><h2 id='card-upload-heading'>카드 업로드</h2><p class='card-workspace-muted'>원본 파일을 먼저 저장한 뒤 백그라운드에서 처리합니다. 화면을 새로 열어도 저장된 처리 상태를 확인할 수 있습니다.</p></div>"
        "<div class='card-workspace-panel-actions'><button type='button' class='card-workspace-secondary' data-card-panel-close='upload'>닫기</button></div></header>"
        "<div id='card-gap-context' class='card-legacy-notice' role='status' hidden></div>"
        "<form class='card-upload-form' onsubmit='return false'>"
        "<label for='card-upload-files'>업로드할 카드 파일 선택</label>"
        + ui_components.file_drop('files', '.xls,.xlsx,.csv', True, '파일을 선택하거나 이곳에 끌어다 놓으세요')
          .replace("<input class=\"sr-only-focusable\"", "<input id='card-upload-files' class=\"sr-only-focusable\" aria-describedby='card-upload-help'")
          .replace("<ul aria-live='polite'>", "<ul id='card-upload-file-list' aria-live='polite'>") +
        "<p id='card-upload-selection' class='card-workspace-muted'>선택된 파일 없음</p>"
        "<p id='card-upload-help' class='card-workspace-muted'>XLS, XLSX, CSV 파일을 한 번에 최대 100개, 합계 99MB까지 선택할 수 있습니다.</p>"
        "<button id='card-upload-submit' type='button' class='card-workspace-secondary'>선택한 파일 업로드</button></form>"
        "<p id='card-upload-status' class='card-workspace-status' role='status' aria-live='polite'></p>"
        "<p id='card-upload-resume-status' class='card-workspace-status' role='status' aria-live='polite' hidden></p>"
        "<ol id='card-upload-results' class='card-upload-results' aria-label='파일별 처리 결과' hidden></ol>"
        f"<section id='card-upload-batch' class='card-upload-batch' aria-live='off'{'' if batch else ' hidden'}></section>"
        "</section>"
        f"<section id='card-coverage-panel' class='card-workspace-panel' aria-labelledby='card-coverage-heading' tabindex='-1'{'' if active == 'coverage' else ' hidden'}>"
        "<header><div><h2 id='card-coverage-heading'>수집 현황</h2><p class='card-workspace-muted'>카드사별 수집 기간을 확인하고, 빈 기간의 자료를 업로드하세요.</p></div>"
        "<div class='card-workspace-panel-actions'><button type='button' class='card-workspace-secondary' id='card-coverage-refresh' aria-label='수집 현황 새로고침'>새로고침</button>"
        "<button type='button' class='card-workspace-secondary' data-card-panel-close='coverage' aria-label='수집 현황 닫기'>닫기</button></div></header>"
        "<p id='card-coverage-status' class='card-workspace-status' role='status' aria-live='polite'></p>"
        "<div id='card-coverage-summary'></div></section>"
        "</section>"
    )


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
        return "기타비용"
    source = str(classification_source or "").strip()
    if source in ('manual', 'user_decision', 'user_exception', 'previous_decision',
                  'inference', 'auto_inferred', 'code_inference', 'ai_inference'):
        label = '수동' if source in ('manual', 'user_decision', 'user_exception', 'previous_decision') else '자동'
        return f"{trip} · {label}"
    return trip


def _classification_source_label(source) -> str:
    from app.assignment_status import classification_source_label
    return classification_source_label(source)


def _classification_chip(item: dict) -> str:
    """Render the short provenance cue while leaving the full basis in detail."""
    source = str(item.get('classification_source') or '').strip().lower()
    if source in {'manual', 'user_decision', 'user_exception', 'previous_decision'}:
        return "<span class='chip chip-neutral'>수동</span>"
    if source in {'inference', 'auto_inferred', 'code_inference', 'ai_inference', 'guide_airfare_evidence'}:
        return "<span class='chip chip-accent' title='규칙 기반 자동 귀속'>자동</span>"
    return ''


def _status_badges(item: dict) -> str:
    """Show source and safety facts only; classification is already resolved."""
    badges: list[str] = []
    if str(item.get("duplicate_of") or "").strip():
        badges.append("<span class='card-all-badge duplicate'>중복 출처</span>")
    if str(item.get("conflict_reason") or "").strip():
        badges.append("<span class='card-all-badge conflict'>원본 충돌</span>")
    return "".join(badges)


def _detail_href(transaction_id) -> str:
    tid = str(transaction_id or "").strip()
    if not tid:
        return ""
    return "/board?" + urlencode({"row": f"card-{tid}"})


def _review_action(item: dict) -> str:
    """Keep one read-only transaction link while removing classification work links."""
    tid, batch = item.get('transaction_id'), item.get('batch_id')
    if not tid or not batch:
        return ""
    href = '/import?' + urlencode({'batch': batch, 'transaction': tid})
    if item.get('duplicate_of'):
        return f"<a class='card-all-link card-review-action' href='{_esc(href + '#preview')}'>중복 근거 확인</a>"
    if item.get('conflict_reason') or item.get('parse_error'):
        return f"<a class='card-all-link card-review-action' href='{_esc(href)}'>원본 문제 확인</a>"
    return f"<a class='card-all-link card-review-action' href='{_esc(href)}'>거래 상세 보기</a>"


def card_detail_html(item: dict) -> str:
    """Escaped source facts; a ledger row is not required and nothing is written."""
    tid = str(item.get('transaction_id') or '').strip()
    from app.assignment_status import assignment_conflict_label, row_assignment
    from app.quarter_tab import parse_tab
    assignment = row_assignment(item, _trip_context()[0].keys())
    # The refund tab is a financial relationship view, not a user destination.
    # Keep the card's actual travel or source-date quarter destination visible
    # in the detail panel; the list still links refund members to the protected
    # refund view separately.
    from app.card_destination import display_destination
    destination = display_destination(item, trip_names=_trip_context()[0])
    from app.classification_provenance import label
    source = label(item)
    source_key = str(item.get('classification_source') or '').strip().lower()
    if source_key in {'manual', 'user_decision', 'user_exception', 'previous_decision'}:
        source = '수동'
    elif source_key in {'inference', 'auto_inferred', 'code_inference', 'ai_inference', 'guide_airfare_evidence'}:
        source = '자동'
    fields = [('가맹점', item.get('merchant')), ('이용일시', item.get('approval_date') or item.get('posting_date') or '원본 날짜 오류'),
              ('금액', _format_amount(item.get('amount_krw'), item.get('foreign_amount'), item.get('foreign_currency'))),
              ('카드', item.get('card_label')), ('승인번호', item.get('approval_number')),
              ('귀속', destination), ('항목', item.get('item')), ('분류 출처', source),
              ('거래 내용', item.get('description')), ('중복 출처', item.get('duplicate_of')),
              ('원본 충돌', item.get('conflict_reason')),
              ('배정 충돌', assignment_conflict_label(assignment['conflicts']))]
    action_html = ''
    basis = str(item.get('classification_basis') or '').strip()
    if basis in ('아직 분류하지 않았어요', '분류 대기', '미분류'):
        basis = '저장된 근거 없음 · 카드 날짜 기준 귀속을 표시합니다.'
    basis_html = (f"<details><summary>저장된 귀속 근거 보기</summary><p>{_esc(basis)}</p></details>"
                  if basis else '')
    destination_tab = str(item.get('display_tab_id') or item.get('trip_id') or '').strip()
    if item.get('refund_tab_member'):
        destination_tab = 'refunds'
    ledger_link = ''
    if destination_tab and tid:
        ledger_link = ("<a class='card-all-ledger-link' href='/board?" +
                       _esc(urlencode({'tab': destination_tab, 'row': 'card-' + tid})) +
                       "'>이 여행 장부에서 보기</a>")
    return (action_html + "<dl class='card-detail-fields'>" + ''.join(
        f'<dt>{_esc(label)}</dt><dd>{_esc(value)}</dd>' for label, value in fields if value not in (None, ''))
        + '</dl>' + basis_html + _review_action(item) + ledger_link)


def _group_by_date(items: list[dict]) -> list[tuple[str, list[tuple[str, str, dict]]]]:
    """날짜 오름차순, 같은 날짜는 시간 있는 거래 먼저, 그다음 안정 ID 순."""
    grouped: dict[str, list[tuple[str, str, dict]]] = {}
    for item in items:
        date_part, time_part = _split_datetime(
            item.get("use_date") or item.get("approval_date"))
        key = date_part or "이용일 원문 없음"
        grouped.setdefault(key, []).append((date_part, time_part, item))
    ordered: list[tuple[str, list[tuple[str, str, dict]]]] = []
    for key in sorted(k for k in grouped if k != "이용일 원문 없음"):
        rows = grouped[key]
        rows.sort(key=lambda row: (row[1] == "", row[1],
                                   str(row[2].get("transaction_id") or "")))
        ordered.append((key, rows))
    if "이용일 원문 없음" in grouped:
        rows = sorted(grouped["이용일 원문 없음"],
                      key=lambda row: str(row[2].get("transaction_id") or ""))
        ordered.append(("이용일 원문 없음", rows))
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
                date_text = "이용일 원문 없음"
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
            from app.card_destination import display_destination
            trip_name = display_destination(item, trip_names=trip_names)
            source = str(item.get("classification_source") or "").strip()
            if item.get('refund_tab_member'):
                trip_markup = "<a class='card-all-link' href='/board?tab=refunds'>취소·환불</a>"
            else:
                trip_markup = (f"<span class='card-all-trip-name' title='{_esc(trip_name)}'>"
                               f"{_esc(trip_name)}</span>")
                from app.classification_provenance import origin, label
                if origin(item) != 'unknown':
                    trip_markup += f"<span class='card-all-trip-source'>{_classification_chip(item)}</span>"
            detail_id = 'card-detail-' + tid
            merchant_markup = f"<span class='merchant-name'>{_esc(merchant)}</span>"
            row_attrs = f" data-detail-id='{_esc(tid)}'" if tid and include_detail_link else ''
            if row_attrs:
                merchant_markup = (f"<button type='button' class='card-all-row-toggle' aria-expanded='false' "
                                   f"aria-controls='{_esc(detail_id)}' aria-label='{_esc(merchant)} 상세 보기'>"
                                   f"{merchant_markup}</button>")
            status = _status_badges(item)
            status_markup = f"<div class='card-all-badges'>{status}</div>" if status else ""
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


def _render_mobile_rows(items: list[dict], *, trip_names: dict[str, str] | None = None,
                        year: int | None = None, month: int | None = None) -> str:
    """Render the compact shared list-row projection used below the mobile breakpoint."""
    rows: list[str] = []
    for _date_key, entries in _group_by_date(items):
        for _date_part, _time_part, item in entries:
            tid = str(item.get('transaction_id') or '').strip()
            if not tid:
                continue
            approved = item.get('use_date') or item.get('approval_date')
            date_text = _period_date(approved, year, month) or '이용일 원문 없음'
            merchant = str(item.get('merchant') or '').strip() or '가맹점 미상'
            amount = _format_amount(item.get('amount_krw'), item.get('foreign_amount'),
                                    item.get('foreign_currency'))
            from app.card_destination import display_destination
            trip_name = display_destination(item, trip_names=trip_names)
            secondary = ' · '.join(value for value in (date_text, trip_name) if value)
            detail_id = 'card-mobile-detail-' + tid
            row = ui_components.list_row(
                merchant, amount, secondary, {'tag': 'button'})
            row = row.replace(
                '<li class="list-row">',
                f"<li class='list-row' data-detail-id='{_esc(tid)}'>", 1)
            row = row.replace(
                '<button type="button" class="lr-hit">',
                f"<button type='button' class='lr-hit card-all-mobile-row-toggle' "
                f"aria-expanded='false' aria-controls='{_esc(detail_id)}'>", 1)
            row = row.replace('</button></li>',
                             f"</button><div class='card-all-mobile-expanded' id='{_esc(detail_id)}' "
                             "hidden><div class='card-all-expanded-content' aria-live='polite'></div></div></li>", 1)
            rows.append(row)
    return ("<ul class='card-all-mobile-list' aria-label='카드 거래 목록'>" +
            ''.join(rows) + '</ul>')


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
        "<th scope='col'>귀속</th>"
        "</tr></thead>"
        f"<tbody>{_render_month_rows(items, trip_names=trip_names, year=year, month=month)}</tbody>"
        "</table></div>" + _render_mobile_rows(items, trip_names=trip_names, year=year, month=month))


def _undated_section(year: int, items: list[dict], count: int, *,
                     expanded: bool, cursor: str | None, has_more: bool,
                     trip_names: dict[str, str] | None = None, filter_state=None) -> str:
    heading = f"<h2>이용일 원문 없음 · {count:,}건</h2>"
    note = "<p class='card-all-muted'>이용일이 없는 거래는 연도와 관계없이 표시합니다.</p>"
    if count == 0:
        return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
                f"<div id='undated-heading'>{heading}</div>"
                + ui_components.empty_state('이용일 원문이 없는 카드 거래가 없습니다.',
                    '기간을 바꾸거나 카드 자료를 추가하면 다시 확인할 수 있습니다.',
                    "<a class='btn ghost' href='/cards/all'>카드 내역으로 돌아가기</a>")
                + "</section>")
    if not expanded:
        href = "/cards/all?" + urlencode({**(filter_state or {}), "year": year, "undated": "1"})
        return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
                f"<div id='undated-heading'>{heading}</div>{note}"
                f"<a class='card-all-link' href='{_esc(href)}'>이용일 원문 없음 목록 보기</a>"
                "</section>")
    more = ""
    if has_more and cursor:
        href = "/cards/all?" + urlencode({**(filter_state or {}), "year": year, "undated": "1",
                                         "undated_cursor": cursor})
        more = ("<div class='card-all-pagination'>"
        f"<a class='card-all-link' href='{_esc(href)}'>다음 이용일 원문 없음 거래 100건 보기</a>"
                "</div>")
    return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
            f"<div id='undated-heading'>{heading}</div>{note}"
            f"{_transactions_table(items, '이용일 원문 없음 거래', trip_names=trip_names)}{more}"
            "</section>")


def _month_detail(year: int, month: int, items: list[dict], cursor, has_more: bool,
                  total: int, *, trip_names: dict[str, str] | None = None, filter_state=None) -> str:
    count_label = '연결 없음' if (filter_state or {}).get('unassigned') else '전체'
    if not items:
        if total:
            start = "/cards/all?" + urlencode({**(filter_state or {}), "year": year, "month": month})
            return ("<section class='card-all-detail'>"
                    f"<h2>{year}년 {month}월 · {count_label} {total:,}건</h2>"
                    "<p class='card-all-muted'>이 위치에는 표시할 거래가 더 없습니다. "
                    f"<a class='card-all-link' href='{_esc(start)}'>처음부터 보기</a></p>"
                    "</section>")
        return ("<section class='card-all-detail card-all-empty'>"
                f"<h2>{year}년 {month}월</h2>"
                + ui_components.empty_state(
                    '이 기간의 카드 거래가 없습니다.',
                    '조회 조건을 바꾸거나 카드 자료를 추가해 주세요.',
                    "<a class='btn ghost' href='/cards/all?panel=upload'>카드 업로드</a>" if not filter_state else
                    "<a class='btn ghost' href='/cards/all'>조회 조건 초기화</a>")
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
                + ui_components.empty_state('검색 결과가 없습니다.', message,
                    "<a class='btn ghost' href='/cards/all'>조회 조건 초기화</a>")
                + "</section>")
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
    return ("<select id='card-period' name='period' aria-label='조회 기간' onchange='this.form.requestSubmit()'>"
            + ''.join(groups) + '</select>')


def _transaction_tabs(current: str) -> str:
    items = [
        {'label': '카드', 'href': '/cards/all', 'key': 'cards'},
        {'label': 'OTA 예약', 'href': '/ota', 'key': 'ota'},
        {'label': '환불', 'href': '/board?tab=refunds', 'key': 'refunds'},
    ]
    try:
        from . import flight_passenger_page
        if flight_passenger_page.enabled():
            items.append({'label': '항공권', 'href': '/flight-passengers', 'key': 'flight'})
    except Exception:
        pass
    return ui_components.section_tabs(items, current).replace('aria-label="섹션"', 'aria-label="거래 종류"')


def _transaction_header(*, owner: bool = False, active_panel: str = '') -> str:
    actions = ''
    if owner:
        actions = ("<button id='card-upload-open' class='btn primary' type='button' "
                   "aria-controls='card-upload-panel' aria-expanded='" +
                   str(active_panel == 'upload').lower() + "'>카드 업로드</button>"
                   "<button id='card-coverage-open' class='btn' type='button' "
                   "aria-controls='card-coverage-panel' aria-expanded='" +
                   str(active_panel == 'coverage').lower() + "'>수집 현황 <span aria-hidden='true' class='chevron-down'>⌄</span></button>")
    return ui_components.page_header('거래', meta='카드 거래와 예약 자료를 확인합니다.', actions=actions, breadcrumb=())


def _available_years(db_path: str | None) -> list[int]:
    result = _ct.available_years(db_path=db_path)
    years = {int(value) for value in result.get("years", []) if str(value).isdigit()}
    years.add(DEFAULT_YEAR)
    return sorted(years, reverse=True)


def _default_db_path():
    from .ledger_board import _get_card_db_path as _board_card_db_path
    return _board_card_db_path()


def _error_page(message: str) -> str:
    body = (CARD_ALL_STYLE + "<div class='card-all-page'>"
            "<section class='card-all-detail card-all-empty' role='alert'>"
            "<h2>카드를 불러오지 못했어요</h2>"
            f"<p>{_esc(message)}</p>"
            "<p>다시 불러온 뒤에도 문제가 계속되면 관리자에게 문의해 주세요.</p>"
            "<a class='site-action' href=''>다시 불러오기</a></section></div>")
    fragment = _design.shell("카드 내역", tab_id="", heading="카드 내역",
                             meta="저장된 카드 거래를 연도와 월로 확인해요.",
                             body=body, home=True)
    return _design.render(fragment, title="카드 내역")


def _strip_legacy_shell_header(fragment: str) -> str:
    """Leave document title ownership to the app shell and transaction header."""
    start = fragment.find("<div class='page-hd'>")
    marker = "</div></div><div class='page-body'>"
    if start < 0:
        return fragment
    end = fragment.find(marker, start)
    if end < 0:
        return fragment
    return fragment[:start] + fragment[end + len("</div></div>"):]


def _upload_workspace_page(query_params, *, owner: bool, csrf: str) -> str:
    """Render direct upload deep links without waiting on the card writer."""
    body = (
        CARD_ALL_STYLE
        + "<div class='card-all-page' data-card-upload-quick-view='true'>"
        + _transaction_header(owner=owner, active_panel=_first(query_params, 'panel', ''))
        + _transaction_tabs('cards')
        + "<div class='card-all-page-loading' role='status' hidden>"
        "<span class='card-all-spinner' aria-hidden='true'></span>불러오는 중</div>"
        + _workspace_html(query_params, owner=owner, csrf=csrf)
        + "<section class='card-all-detail card-all-empty' role='status'>"
        "<h2>업로드 후 확인</h2>"
        "<p>업로드를 마친 뒤 이 화면에서 거래와 수집 현황을 확인할 수 있습니다.</p>"
        "<p>업로드 패널을 닫으면 카드 내역을 다시 불러옵니다.</p>"
        "</section></div>" + CARD_ALL_SCRIPT
        + (f"<script>{CARD_HISTORY_WORKSPACE_SCRIPT}</script>" if owner else "")
    )
    fragment = _design.shell(
        "카드 내역", tab_id="", heading="카드 내역",
        meta="카드 거래와 거래일자 공백을 확인해요.", body=body, home=True,
        quick_view=True)
    fragment = _strip_legacy_shell_header(fragment)
    return _design.render(fragment, title="카드 내역")


def cards_all_page(query_params: dict, *, db_path: str | None = None,
                   owner: bool = False, csrf: str = "") -> str:
    operation = 'card_search' if _first(query_params, 'q', '') else 'first_render'
    with request_metrics.card_scope(operation):
        return _cards_all_page(query_params, db_path=db_path, owner=owner, csrf=csrf)


def _cards_all_page(query_params: dict, *, db_path: str | None = None,
                    owner: bool = False, csrf: str = "") -> str:
    """카드 내역 페이지를 그린다. 조회 데이터는 읽기만 수행한다."""
    if _first(query_params, 'panel') == 'upload':
        return _upload_workspace_page(query_params, owner=owner, csrf=csrf)
    year, selected_month, cursor, undated_cursor, show_undated = _request_params(query_params)
    filter_state = _filter_state(query_params)
    trip_names = {}
    card_db_path = db_path or _default_db_path()
    if not card_db_path:
        return _error_page("카드 원본 DB가 연결되지 않았어요. 운영 설정을 확인해 주세요.")
    try:
        trip_names, valid_trip_ids = _trip_context()
        filters = {'card': filter_state.get('card', ''), 'search': filter_state.get('q', '')}
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
                                         cursor=cursor, per_page=PAGE_SIZE,
                                         known_total=sum(months.values()), **filters)
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
                per_page=UNDATED_PAGE_SIZE, known_total=undated_count, **filters)
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

    with request_metrics.card_phase('card_render'):
        selected_card = filter_state.get('card', '')
        options = "<option value=''>전체 카드</option>" + ''.join(
            f"<option value='{_esc(option['card_key'])}'{' selected' if option['card_key'] == selected_card else ''}>{_esc(option['card_label'])}</option>"
            for option in card_options)
        hidden_filter_state = {'undated': '1'} if show_undated else {}
        active_panel = _first(query_params, 'panel', '')
        if owner:
            for key in ('panel', 'batch', 'transaction', 'gap_card', 'gap_start', 'gap_end',
                        'gap_issuer', 'gap_basis', 'legacy_cleanup', 'legacy_import'):
                value = str(_first(query_params, key, '') or '')
                if value and len(value) <= 220:
                    hidden_filter_state[key] = value
        reset_href = '/cards/all?' + urlencode({
            'year': year,
            **({'month': selected_month} if selected_month else {}),
            **({'panel': active_panel} if owner and active_panel in ('upload', 'coverage') else {}),
        })
        filter_form = ui_components.filter_bar([
            {'label': '기간', 'control_html': _period_select(year, selected_month, years)},
            {'label': '카드', 'control_html': f"<select id='card-filter' name='card' aria-label='카드별 조회'>{options}</select>"},
            {'label': '검색', 'control_html': f"<input id='card-q' type='search' name='q' value='{_esc(filter_state.get('q', ''))}' placeholder='카드사·끝4자리·가맹점·내용·분류·금액·승인번호'>"},
        ], submit_label='조회', reset_href=reset_href)
        filter_form = filter_form.replace('<form class="filter-bar"', "<form class='filter-bar' action='/cards/all' aria-label='조회 조건'")
        filter_form = filter_form.replace('<button class="btn primary"', '<button class="btn"')
        filter_form = filter_form.replace('</form>', _hidden_filters(hidden_filter_state) + '</form>')
        filter_form = filter_form.replace('>초기화</a>', '>' + ui_icons.icon('rotate-ccw', 14) + '초기화</a>')

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
            + _transaction_header(owner=owner, active_panel=active_panel)
            + _transaction_tabs('cards')
            + "<div class='card-all-page-loading' role='status' hidden>"
            "<span class='card-all-spinner' aria-hidden='true'></span>불러오는 중</div>"
            + _workspace_html(query_params, owner=owner, csrf=csrf)
            + filter_form
            + detail
            + _undated_section(year, undated_items, undated_count, expanded=show_undated, cursor=undated_next_cursor, has_more=undated_has_more, trip_names=trip_names, filter_state=filter_state)
            + "</div>" + CARD_ALL_SCRIPT
            + (f"<script>{CARD_HISTORY_WORKSPACE_SCRIPT}</script>" if owner else ""))
        fragment = _design.shell(
            "카드 내역", tab_id="", heading="카드 내역",
            meta="카드 거래와 거래일자 공백을 확인해요.",
            body=body, home=True)
        fragment = _strip_legacy_shell_header(fragment)
        return _design.render(fragment, title="카드 내역")
