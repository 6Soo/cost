"""A/Ramp/Pretendard design applied to the real ledger screens.

The screen is server rendered and talks to the existing store, save, upload,
export and rule dialog contracts. Nothing in this module re-implements them,
and no demo data or demo JavaScript is copied in: the demo only supplied the
layout, the colours and the font.

Static fonts and OTA icons are served from explicit allowlists, so a path
cannot escape their asset directories.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

from . import ledger_board as board
from . import read_scope, ui_icons

FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
OTA_DIR = Path(__file__).resolve().parent / "static" / "ota"
OTA_ASSETS = {"agoda.png": "image/png", "trip.png": "image/png"}


def ota_asset(name):
    if not isinstance(name, str) or name not in OTA_ASSETS:
        return None
    path = OTA_DIR / name
    if not path.is_file() or path.resolve().parent != OTA_DIR.resolve():
        return None
    return path.read_bytes(), OTA_ASSETS[name]


def _category_icon(row):
    category = _row_item(row)
    for terms, name in ((('항공',), 'plane'), (('숙박', '호텔'), 'bed'),
                        (('교통',), 'bus'), (('식비',), 'utensils'),
                        (('현지',), 'map-pin')):
        if any(term in category for term in terms):
            return ui_icons.icon(name, size=14)
    return ui_icons.icon('receipt', size=14)


def _merchant_icon(row):
    # Only the source merchant identifies a brand. Notes and booking IDs do not.
    merchant = str(row.get('source_merchant') or '').upper()
    asset = None
    if re.search(r'(?<![A-Z0-9])AGODA(?![A-Z0-9])', merchant):
        asset = 'agoda.png'
    elif '트립닷컴' in merchant or re.search(r'(?<![A-Z0-9])TRIP\.COM(?![A-Z0-9.])', merchant):
        asset = 'trip.png'
    if asset:
        return (f"<img class='ota-icon' src='/assets/ota/{asset}' width='18' height='18' "
                "alt='' aria-hidden='true' loading='lazy' decoding='async'>")
    return ui_icons.icon('receipt', size=16)

# Explicit allowlist. A name that is not a key here is refused, whatever it
# contains, so traversal, absolute paths and encoded separators cannot resolve.
STATIC_ASSETS = {
    "PretendardVariable.woff2": "font/woff2",
    "OFL.txt": "text/plain; charset=utf-8",
}

FONT_FAMILY = "Pretendard Variable"

# Stored values stay English; the screen shows the Korean the app already uses.
INCOME_KIND_LABELS = {
    "deposit": "예약금",
    "balance": "잔금",
    "additional": "추가금",
}

# Buttons and rows keep the values the existing tests and the export already use.
MONEY = "{:,}원"


def static_asset(name: str):
    """Return (bytes, content_type) for an allowed asset, or None."""
    if not isinstance(name, str) or name not in STATIC_ASSETS:
        return None
    path = FONT_DIR / name
    if path.parent.resolve() != FONT_DIR.resolve():
        return None
    if not path.is_file():
        return None
    return path.read_bytes(), STATIC_ASSETS[name]


# --------------------------------------------------------------------- chrome
STYLE = """
@font-face{
 font-family:"Pretendard Variable";
 src:url("/assets/fonts/PretendardVariable.woff2") format("woff2-variations"),
     url("/assets/fonts/PretendardVariable.woff2") format("woff2");
 font-weight:100 900;font-style:normal;font-display:swap;
}
*{box-sizing:border-box}
:root{
 --bg:#F8FAFC;--paper:#FFFFFF;--ink:#0F172A;--mut:#475569;--line:#E2E8F0;
 --line2:#F1F5F9;--line-strong:#D0D5DD;--hover:#F8FAFC;--focus:#2266F5;
 --sel:#ECF5EF;--grn:#1C7A52;--grn-dk:#166444;--grn-lt:#F1F7F3;
 --warn:#B54708;--neg:#B42318;--bad:#B42318;
}
@media(prefers-color-scheme:dark){
:root{
 --bg:#0F172A;--paper:#1E293B;--ink:#F8FAFC;--mut:#94A3B8;--line:#334155;
 --line2:#334155;--line-strong:#475569;--hover:#334155;--focus:#93C5FD;
 --sel:#1E3A5F;--grn:#1C7A52;--grn-dk:#A7F3D0;--grn-hover:#166444;--grn-lt:#14532D;
 --warn:#FBBF24;--neg:#FDA4AF;--bad:#FDA4AF;
}
}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);
 font:400 14px/1.5 "Pretendard Variable","Pretendard",system-ui,-apple-system,
   "Segoe UI",Roboto,"Malgun Gothic",Apple SD Gothic Neo,sans-serif;
 word-break:keep-all;-webkit-text-size-adjust:100%}
button,input,select,textarea{font:inherit;color:inherit}
.tnum{font-variant-numeric:tabular-nums}
h1,h2,p{margin:0}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
input:focus,select:focus,textarea:focus{border-color:var(--focus)!important;
 box-shadow:0 0 0 3px rgba(34,102,245,.12);outline:none}
.synth{display:inline-block;font-size:11.5px;line-height:17px;padding:0 7px;border:1px solid var(--line);
 border-radius:6px;color:var(--mut);margin-left:8px;vertical-align:2px}

.app{display:flex;height:100dvh;min-height:0}
.work-menu{padding:12px 24px;border-bottom:1px solid var(--line);background:var(--paper)}
.work-menu h2{font-size:14px;margin:0 0 8px}
.work-actions{display:flex;flex-wrap:wrap;gap:8px}
.work-action{flex:1 1 170px;min-width:0;padding:10px 12px;border:1px solid var(--line);
 border-radius:8px;color:var(--ink);text-decoration:none;overflow-wrap:anywhere;
 display:flex;align-items:flex-start;gap:8px}
.work-action>span{flex:1 1 auto;min-width:0}
.work-action strong,.work-action small{display:block}
.work-action small{font-size:12px;color:var(--mut);margin-top:3px}
a.work-action:hover{background:var(--hover);border-color:var(--grn)}
.nav .work-menu{padding:10px 12px;flex:none}
.nav .work-actions{display:grid;grid-template-columns:1fr}
.nav .work-action{padding:8px 10px;font-size:12px}
.nav .work-action small{display:none}
.income-note{padding:0 24px 12px;color:var(--mut);font-size:12.5px}
.main-wrap{max-width:1180px;padding:24px;margin:0 auto}
.main-wrap .page-hd{padding:0 0 20px}
.main-wrap .page-hd>div:first-child{min-width:0}
.main-wrap .bar,.main-wrap .sum{padding-left:0;padding-right:0}
.main-wrap .status:empty{display:none}
.main-wrap .status,.main-wrap .income-note{padding-left:0;padding-right:0}
.main-wrap #global-state,.main-wrap #live-status-wrap{padding-left:0!important;padding-right:0!important}
.main-wrap .act{flex:1 1 420px;justify-content:flex-end;max-width:100%}
.main-wrap .period,.main-wrap .meta>span,.main-wrap .sum i{display:inline-flex;align-items:center;gap:6px}
.main-wrap .meta .btn{height:28px;font-size:12px}
.main-wrap .sum{align-items:center;padding-top:16px;padding-bottom:16px}
.main-wrap .sum .scope{width:100%;font-size:12px;color:var(--mut);margin-bottom:-16px}
.main-wrap #tbl td:first-child,.main-wrap #tbl th:first-child{padding-left:0}
.income-sync{display:flex;align-items:center;flex-wrap:wrap;gap:6px 10px;color:var(--mut);font-size:12px;margin:0 0 16px}
.income-status{font-size:15px;font-weight:600;display:flex;align-items:center;gap:8px}
@media(max-width:759px){.main-wrap .act{justify-content:flex-start;flex-basis:100%}.main-wrap .lst .li{padding-left:0;padding-right:0}}
#trip-income{margin:12px 0}
#trip-income h2{display:flex;align-items:center;gap:8px;font-size:18px;line-height:1.5;margin-bottom:8px}
#trip-income>.muted{font-size:13px;line-height:1.6;margin-bottom:12px}
#google-trip-income{padding:16px 24px;border:1px solid var(--line);border-radius:12px;background:var(--bg);font-size:14px}
#google-trip-income summary{display:flex;align-items:center;gap:8px;min-height:44px;cursor:pointer;font-size:16px;font-weight:600;color:var(--ink);list-style:none}
#google-trip-income summary::after{content:'▾';margin-left:auto}
#google-trip-income:not([open]) summary::after{content:'▸'}
#google-trip-income p{line-height:1.7;margin:8px 0 12px}
#google-trip-income .google-income-help{font-size:12.5px;color:var(--mut);margin-bottom:0}
#google-trip-income .btn{margin:0 8px 12px 0;min-height:36px}
#google-trip-income .google-income-scroll{overflow-x:auto;margin:4px 0 16px;background:var(--paper);border:1px solid var(--line);border-radius:8px}
#google-trip-income table{font-size:13px;min-width:700px}
#google-trip-income caption{padding:10px 14px;text-align:left;font-weight:600}
#google-trip-income td,#google-trip-income th{padding:10px 14px;white-space:nowrap}
#google-trip-income td:nth-child(n+4),#google-trip-income th:nth-child(n+4){text-align:right;font-variant-numeric:tabular-nums}
#google-trip-income .income-total{white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}
#google-trip-income th .ic{width:14px;height:14px;vertical-align:-2px;margin-right:4px}
@media(max-width:759px){
 #google-trip-income .google-income-scroll{overflow:visible}
 #google-trip-income table{min-width:0;width:100%;table-layout:fixed}
 #google-trip-income .income-breakdown{display:none}
 #google-trip-income .income-date{width:26%;white-space:normal;overflow-wrap:anywhere}
 #google-trip-income .income-person{width:32%;white-space:normal;overflow-wrap:anywhere}
 #google-trip-income .income-total{width:42%;overflow:visible;text-overflow:clip;font-size:12px}
 #google-trip-income td,#google-trip-income th{padding:10px 5px}
 #google-trip-income caption{padding:10px 5px}
}
.main-wrap #global-state,.main-wrap #live-status-wrap{padding:0 24px;font-size:12px;line-height:1.6}
.main-wrap .s-main{font-size:14px;line-height:1.5}
.main-wrap .s-sub{font-size:12.5px;line-height:1.5;margin-top:3px}
.main-wrap #tbl td:last-child,.main-wrap #tbl th:last-child{padding-right:24px}
@media(max-width:759px){.main-wrap{padding:16px 16px 20px;max-width:none}}
@media(max-width:759px){#google-trip-income{padding:10px 12px}.main-wrap #global-state,.main-wrap #live-status-wrap{padding:0 16px}}
@media(max-width:759px){.main-wrap .sum{gap:10px 18px}.main-wrap .sum .scope{margin-bottom:-4px}.main-wrap .page-hd{padding-bottom:14px}}
@media(max-width:759px){
 .work-menu{padding:10px 16px}
 .work-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
 .work-action{padding:9px 10px;font-size:13px}
 .income-note{padding:0 16px 12px}
}
.nav{width:232px;flex:0 0 232px;background:var(--bg);border-right:1px solid var(--line);
 display:flex;flex-direction:column;min-height:0;overflow:auto}
.nav-hd{padding:18px 16px 14px}
.nav-hd a.brand{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;text-align:center}
.nav-hd .brand img{width:20px;height:20px;margin:0;flex:0 0 auto}
.brand{font-size:15.5px;font-weight:700;letter-spacing:-.01em}
.brand small{display:block;font-size:11.5px;font-weight:400;color:var(--mut);margin-top:3px}
a.brand{display:block;color:inherit;text-decoration:none;border-radius:6px}
a.brand:hover{background:var(--hover)}
a.brand:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.nav-sec{padding:12px 16px 6px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.05em}
.site-links{display:grid;gap:4px;margin:0;padding:8px 12px}
.site-links a{display:flex;align-items:center;gap:8px;min-height:40px;padding:8px;
 border-radius:6px;text-decoration:none;color:inherit}
.site-links a:hover{background:var(--hover)}
.site-links a[aria-current=page]{background:var(--sel);font-weight:600}
.site-links .nm{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav-q{margin:0 12px 6px}
.nav-q input{width:100%;height:32px;border:1px solid var(--line-strong);border-radius:7px;
 background:var(--paper);padding:0 8px;font-size:13px}
.nav-list{list-style:none;margin:0;padding:0 8px}
.nv{display:flex;align-items:center;gap:8px;width:100%;min-height:36px;padding:6px 8px;
 border:0;border-left:2px solid transparent;border-radius:7px;background:transparent;
 font-size:14px;font-weight:400;text-align:left;cursor:pointer;color:var(--ink);text-decoration:none}
.nv:hover{background:var(--hover)}
.nv[aria-pressed="true"],.nv.sel{background:var(--sel);border-left-color:var(--grn);font-weight:600}
.nv .nm{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nv .ct{flex:0 0 auto;margin-left:8px;font-size:12px;color:var(--mut);white-space:nowrap}
.nv .ct.warn{color:var(--warn)}
.nav-arch .nm{color:var(--mut)}
.nav-toggle{border-left:2px solid transparent;margin:0 8px;max-width:calc(100% - 16px)}
.nav-toggle .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav-toggle .ct{flex:0 0 auto}
.nav-toggle[aria-expanded="true"]{background:var(--hover)}
.arch-row{display:flex;align-items:center;gap:6px}
.arch-row .nv{flex:1 1 auto}
.arch-restore{margin:0;display:flex}
.arch-restore .btn,.arch-view{height:28px;padding:0 8px;font-size:12px;font-weight:500}
.arch-view{margin-left:6px}
.page-body{padding:0 0 28px}
#q-go{height:32px}
#q-clear{height:32px}
.nav-ft{margin-top:auto;padding:12px 16px;border-top:1px solid var(--line);
 font-size:11.5px;color:var(--mut);line-height:1.6}
#live-nav{display:flex;flex-direction:column;flex:1 0 auto}
#previous-trips{margin-top:auto;padding:12px 8px;border-top:1px solid var(--line)}
#previous-trips>summary{cursor:pointer;min-height:44px;list-style:none}
#previous-trips[open]>summary>span:first-child{transform:rotate(90deg)}
.nav-mask{display:none}

.main{flex:1 1 auto;min-width:0;overflow:auto;background:var(--paper)}
.page-hd{display:flex;align-items:flex-start;gap:16px;padding:22px 24px 16px;
 border-bottom:1px solid var(--line)}
.page-hd h1{font-size:21px;font-weight:700;letter-spacing:-.018em;line-height:1.25}
.period{font-size:13px;color:var(--mut);margin-top:3px}
.meta{font-size:12.5px;color:var(--mut);margin-top:6px;display:flex;flex-wrap:wrap;gap:4px 14px}
.meta a{color:var(--mut)}
.act{margin-left:auto;display:flex;gap:8px;flex:0 0 auto;flex-wrap:wrap}
.bar{display:flex;align-items:center;gap:10px;padding:10px 24px;border-bottom:1px solid var(--line);
 flex-wrap:wrap}
#q{height:32px;width:280px;max-width:52vw;border:1px solid var(--line-strong);border-radius:7px;
 padding:0 8px;background:var(--paper)}
#kind{height:32px;border:1px solid var(--line-strong);border-radius:7px;background:var(--paper);
 padding:0 6px;font-weight:500}
.crumb{font-size:12.5px;color:var(--mut)}
.status{padding:7px 24px;font-size:12.5px;color:var(--grn);border-bottom:1px solid var(--line2);
 min-height:30px}
.status.hint{color:var(--mut)}
.status.err{color:var(--neg)}

.sum{display:flex;align-items:baseline;gap:28px;padding:11px 24px;border-bottom:1px solid var(--line);
 flex-wrap:wrap}
.sum div{display:flex;align-items:baseline;gap:7px}
.sum i{font-style:normal;font-size:12px;color:var(--mut)}
.sum b{font-size:17px;font-weight:700;letter-spacing:-.012em}
.sum .n{margin-left:auto;font-size:12.5px;color:var(--mut)}

.tw{padding:0 0 28px}
table{width:100%;table-layout:fixed;border-collapse:collapse}
th,td{padding:0 10px;height:36px;border-bottom:1px solid var(--line2);
 text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
thead th{position:sticky;top:0;z-index:2;height:32px;background:var(--paper);
 font-size:12.5px;font-weight:600;color:var(--mut);border-bottom:1px solid var(--line);
 box-shadow:0 1px 0 var(--line)}
/* 거래처·내용: the counterparty and the content share one cell, so the amount sits
   against the line that explains it. The first line is what the row is, the
   second is who it was with, and both are the row's own values: a merchant equal
   to the content is not printed twice. */
td.c-party{white-space:normal;line-height:1.35;padding:0 6px}
.party-line{display:flex;align-items:center;gap:6px;min-width:0}
td.c-stay{white-space:nowrap;font-size:12.5px;color:var(--mut)}
.party-copy{display:block;min-width:0;flex:1}
.party-line>svg,.ota-icon{flex:none;width:18px;height:18px;object-fit:contain;color:var(--muted,#718096)}
.category-line{display:inline-flex;align-items:center;gap:5px;min-width:0}
.category-line>svg{flex:none;color:var(--muted,#718096)}
.mobile-party .t{min-width:0;flex:1}
.s-main{display:block;font-weight:500;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.s-sub{display:block;font-size:11.5px;color:var(--mut);overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
td.c-note{font-size:13px;color:var(--mut)}
td.c-amt{font-weight:600}
tbody.grp th{height:30px;background:var(--bg);font-size:12.5px;font-weight:600;color:var(--mut);
 border-bottom:1px solid var(--line)}
tbody.grp td{height:30px;background:var(--bg);text-align:right}
tbody.grp .btn{height:24px;font-size:12px}
tr[data-id]{cursor:pointer}
tr[data-id]:hover{background:var(--hover)}
tr[data-id]:focus-visible{outline:2px solid var(--focus);outline-offset:-2px}
tr[aria-selected="true"]{background:var(--sel);box-shadow:inset 2px 0 0 var(--grn)}
.num{text-align:right}
.a-in{color:var(--grn);font-weight:500}
.a-ex{font-weight:500}
.a-neg{color:var(--neg);font-weight:500}
.tag{display:inline-block;font-size:11px;line-height:17px;padding:0 6px;border:1px solid var(--line);
 border-radius:6px;color:var(--mut);font-weight:500}
.tag.in{border-color:#CFE3D7;background:var(--grn-lt);color:var(--grn-dk)}
/* Waiting and cancelled are said in words, not by colour alone, and both come
   from the row itself: no travel assigned, or a cancellation in the source. */
.tag.wait{border-color:#E8D8B4;background:#FBF4E6;color:var(--warn)}
.tag.cancel{text-decoration:line-through}
.empty td{color:var(--mut);text-align:center;height:64px}
.psel{height:30px;width:132px;border:1px solid var(--line-strong);border-radius:7px;background:var(--paper);
 font-size:12.5px;padding:0 4px}
.lst{display:none}

#panel-slot{display:flex;min-height:0}
.panel{width:400px;flex:0 0 400px;background:var(--paper);border-left:1px solid var(--line);
 display:flex;flex-direction:column;min-height:0}
.panel:focus{outline:none}
.p-hd{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;
 padding:16px 18px;border-bottom:1px solid var(--line)}
.p-hd h2{font-size:15px;font-weight:700}
.p-amt{font-size:21px;font-weight:700;letter-spacing:-.018em;margin-top:2px}
/* The save form is a flex child of .panel, so it has to pass the column on.
   Without this .p-bd grows to its content height, stops being a scroller and
   pushes the 저장/취소 footer past the panel bottom, where it cannot be
   reached on a short viewport. */
.panel form{display:flex;flex-direction:column;flex:1 1 auto;min-height:0}
.p-bd{padding:18px;overflow:auto;flex:1 1 auto;min-height:0}
/* The source identifier, the revision and the source kind are a support answer,
   not a working day. They are folded away by default and one click away, and the
   values themselves are unchanged: this moves them, it does not tidy them. */
.p-src{margin:0 0 15px;border:1px solid var(--line);border-radius:8px;background:var(--bg)}
.p-src>summary{cursor:pointer;padding:7px 10px;font-size:12px;color:var(--mut);
 list-style:none;user-select:none}
.p-src>summary::-webkit-details-marker{display:none}
.p-src>summary::after{content:" 더보기";color:var(--grn-dk)}
.p-src[open]>summary::after{content:" 접기"}
.p-src[open]>summary{border-bottom:1px solid var(--line2)}
.p-src .p-sub{margin:0;padding:9px 10px;line-height:1.7}
.p-sub{font-size:12.5px;color:var(--mut);margin-bottom:14px;word-break:break-all}
.f{margin-bottom:15px}
.f label{display:block;font-size:12px;font-weight:500;color:var(--mut);margin-bottom:6px}
.f input,.f select,.f textarea{width:100%;height:38px;border:1px solid var(--line-strong);
 border-radius:7px;padding:0 9px;background:var(--paper);font-weight:500}
.f textarea{height:auto;min-height:64px;padding:8px;resize:vertical}
.f input[readonly],.f select[disabled]{background:var(--bg);color:var(--mut)}
.f .err{color:var(--neg);font-size:12.5px;margin-top:6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.src{font-size:12px;color:var(--mut);background:var(--bg);border:1px solid var(--line);
 border-radius:8px;padding:12px;line-height:1.7}
.p-links{display:flex;flex-wrap:wrap;gap:12px;margin-top:14px;font-size:12.5px}
.p-links a{color:var(--grn-dk)}
.sect{margin:0;padding:20px 24px;border-bottom:1px solid var(--line)}
.sect h2{font-size:16px;font-weight:700;margin-bottom:10px}
/* The actual-source preview. Cards rather than a table, at every width: it
   holds a source locator, which is long and has no spaces to break on, and a
   table would either overflow sideways on a phone or clip the one value a
   reader needs to check against the original. A card cannot overflow that way. */
.src-preview{margin:0.75rem 0;padding:12px 16px;border:1px solid var(--line);
 border-radius:8px;background:var(--bg)}
.src-preview h2{font-size:15px;font-weight:700;margin-bottom:6px}
.src-hd{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.src-hd h2{margin-bottom:0}
.src-list{list-style:none;margin:0;padding:0}
.src-row{border-top:1px solid var(--line2);padding:8px 0}
.src-row:first-child{border-top:0}
.src-line{display:flex;gap:8px;margin:0 0 2px;font-size:13px;align-items:baseline}
.src-line span{flex:0 0 4.5em;color:var(--mut);font-size:12px}
.src-line b{font-weight:600;min-width:0;overflow-wrap:anywhere}
.src-line code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 font-size:12px;overflow-wrap:anywhere}
@media (max-width:759px){
 .src-line{flex-wrap:wrap}
 .src-line span{flex:0 0 100%}
}
.sect h3{font-size:14px;font-weight:600;margin:18px 0 8px}
.sect p{margin:0 0 8px;font-size:13.5px}
.sect .kv{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:13px;color:var(--mut)}
.sect .kv b{color:var(--ink);font-weight:600}
.card2{border:1px solid var(--line);border-radius:8px;padding:16px;margin:0 0 12px}
.card2 h3{font-size:15px;font-weight:700;margin:0 0 6px}
.hist{width:100%;font-size:13px}
.hist th,.hist td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line2);height:auto}
.hist th{background:var(--bg);font-size:12px;color:var(--mut);font-weight:600}
.inline{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-top:10px}
.inline .f{margin:0;min-width:180px;flex:1 1 180px}
.alloc{width:100%;table-layout:fixed;border-collapse:collapse}
.alloc th,.alloc td{padding:6px 8px;border-bottom:1px solid var(--line2);height:auto;
 text-align:left;vertical-align:middle}
.alloc th{font-size:12px;font-weight:600;color:var(--mut);background:var(--bg)}
.page-body table.alloc input,.page-body table.alloc select{
 width:100%;min-width:0;max-width:100%;height:32px}
@media (max-width:759px){
 /* one allocation becomes a labelled field instead of a squeezed row */
 .alloc,.alloc tbody,.alloc tr,.alloc td{display:block;width:100%}
 .alloc thead{display:none}
 .alloc tr{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:0 0 10px}
 .alloc td{border-bottom:0;display:grid;grid-template-columns:96px 1fr;gap:10px;
  align-items:center;padding:4px 0}
 .alloc td::before{content:attr(data-label);font-size:12px;color:var(--mut)}
 .page-body table.alloc input,.page-body table.alloc select{min-width:0;font-size:16px}
}

/* The row and trip screens keep their own markup. These rules only make that
   markup look like the rest of the app; they do not change what it means. */
.page-body h2{font-size:18px;font-weight:700;margin:0 0 12px}
.page-body h3{font-size:14px;font-weight:600;margin:18px 0 8px}
.page-body p{margin:0 0 8px}
.page-body .muted{color:var(--mut);font-size:13px}
.page-body ul{margin:0 0 12px;padding-left:18px}
.page-body li{margin:0 0 4px}
.page-body label{display:inline-block;font-size:12px;color:var(--mut);margin:0 6px 4px 0}
.page-body input:not([type=radio]):not([type=checkbox]),.page-body select{
 width:auto;min-width:220px;max-width:100%;height:34px;padding:0 8px;
 border:1px solid var(--line-strong);border-radius:7px;background:var(--paper);font-weight:500}
.page-body input[type=radio],.page-body input[type=checkbox]{
 width:18px;height:18px;min-width:0;max-width:18px;margin:0;padding:0;
 accent-color:var(--grn);flex:0 0 auto}
/* the label is the target, so the whole row is comfortable to tap */
.opt{display:inline-flex;align-items:center;gap:8px;min-height:44px;
 margin:0 18px 0 0;padding:0 8px 0 0;cursor:pointer;white-space:nowrap}
.qgroup{margin:0 0 20px;padding:0 0 18px;border-bottom:1px solid var(--line2)}
.qgroup:last-of-type{border-bottom:0;padding-bottom:0}
.qgroup p{margin:0 0 6px}
.page-body textarea{min-width:320px;min-height:64px;padding:8px;
 border:1px solid var(--line-strong);border-radius:7px}
.page-body button,.page-body a.btn{
 height:34px;padding:0 12px;margin:6px 6px 0 0;border:1px solid var(--line-strong);
 border-radius:7px;background:var(--paper);font-size:14px;font-weight:600;
 cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}
.page-body .card{border:1px solid var(--line);border-radius:8px;padding:16px;margin:0 0 12px}
.page-body table{border:1px solid var(--line);border-radius:8px;overflow:hidden}
.page-body td,.page-body th{border-bottom:1px solid var(--line2);height:auto;padding:7px 10px}
.page-body a{color:var(--grn-dk)}
@media (max-width:759px){
 .page-body input,.page-body select,.page-body textarea{min-width:0;width:100%;font-size:16px}
 .page-body button,.page-body a.btn{height:44px;width:100%;justify-content:center}
}
.p-ft{display:flex;align-items:center;gap:6px;padding:12px 18px;border-top:1px solid var(--line);
 background:var(--paper)}
/* 저장/취소 carry the panel footer and stay equal. The two walking buttons are
   shown only when there is a row to walk to, and they keep their width so the
   footer does not reflow as the position beside them changes. */
.p-ft .btn{flex:1 1 auto;min-width:0}
.p-ft .p-nav{flex:0 0 auto;padding:0 9px;font-weight:500}
.p-count{flex:0 0 auto;font-size:11.5px;color:var(--mut);white-space:nowrap;
 padding:0 2px}
/* The save and cancel shortcuts are printed on the buttons, so the keyboard
   path is discoverable without a manual (DETAILED_CONTRACT 12.3). */
.kbd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
 line-height:1;padding:2px 4px;margin:0 1px;border:1px solid var(--line);
 border-radius:5px;background:var(--bg);color:var(--mut);font-weight:600}
/* A field the server refused is marked with text and a symbol, never by
   colour alone, and it is the first thing a screen reader reaches. */
.f-err{border-color:var(--bad)!important;box-shadow:0 0 0 2px rgba(180,35,24,.18)}
.f-flag{display:block;font-size:12px;font-weight:600;color:var(--bad);
 margin-top:4px}
.f-flag::before{content:"\26A0 "}
@media (max-width:390px){
 .kbd{display:none}
}

.btn{height:32px;padding:0 10px;border:1px solid var(--line-strong);border-radius:7px;
 background:var(--paper);font-size:13.5px;font-weight:600;cursor:pointer;color:var(--ink);
 white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px}
.btn:hover{background:var(--hover)}
.btn.primary{background:var(--grn);border-color:var(--grn);color:#fff}
.btn.primary:hover{background:var(--grn-hover,var(--grn-dk))}
.btn[disabled]{opacity:.45;cursor:default}
.btn[disabled]:hover{background:var(--paper)}
/* 작은 선형 아이콘: 문구 왼쪽 16px, 장식은 클릭을 부모 버튼에 전달한다. */
.btn .ic,.page-body button .ic,.page-body a.btn .ic{width:16px;height:16px;flex:0 0 auto;pointer-events:none}
.nv .ic,.site-links a .ic{width:18px;height:18px;flex:0 0 auto;pointer-events:none}
.work-action .ic{width:16px;height:16px;flex:0 0 auto;pointer-events:none}
.work-action{transition:border-color .15s,background .15s}
@media(prefers-reduced-motion:reduce){
 .work-action,.btn,.nv{transition:none}
}
.icon{width:32px;height:32px;border:1px solid var(--line-strong);border-radius:7px;background:var(--paper);
 cursor:pointer;font-size:14px;line-height:1;display:inline-flex;align-items:center;justify-content:center}
.icon .ic{width:18px;height:18px;pointer-events:none}
#btn-menu{display:none;font-size:15px}
[hidden]{display:none!important}

@media (max-width:1099px){
.panel{position:fixed;top:0;right:0;bottom:0;z-index:30;width:min(400px,100%);
  box-shadow:-10px 0 28px rgba(16,24,40,.10)}
}
@media (max-width:759px){
 #btn-menu{display:inline-flex;width:44px;height:44px;align-items:center;justify-content:center}
 /* The bar is inside #main, the page's own scrollport. Keep the menu control
    with that scrollport so long expense lists do not strand navigation. */
 .bar{position:sticky;top:0;z-index:3;background:var(--paper)}
 .tw thead th{top:var(--mobile-bar-height,0px)}
 .nav{position:fixed;top:0;left:0;bottom:0;z-index:45;transform:translateX(-100%);
  transition:transform .18s ease;border-right:1px solid var(--line)}
 .nav.open{transform:none}
 .nav-mask{display:block;position:fixed;inset:0;z-index:44;background:rgba(16,24,40,.38)}
 .nav-mask[hidden]{display:none!important}
 .tw{display:none}
 .lst{display:block;padding-bottom:24px}
 .panel{top:0;left:0;right:0;width:auto;z-index:60;border-left:0}
 .btn{height:44px;padding:0 14px}
 .icon{width:44px;height:44px}
 .psel{height:44px;width:100%}
 .page-hd{padding:13px 16px 11px;flex-wrap:wrap;gap:8px}
 .page-hd h1{font-size:20px}
 .page-hd .meta{display:none}
 .period{font-size:12.5px}
 .act{margin-left:auto;width:auto}
 .act .btn{height:40px;padding:0 10px;font-size:13.5px}
  .bar{padding:8px 16px;gap:8px}
  #q{flex:1 1 0;min-width:0;width:auto;max-width:none;height:40px}
  #kind{flex:0 0 96px;min-width:0;height:40px}
  .bar .crumb{display:none}
  #q,#kind,.psel,.f input,.f select,.f textarea,.nav-q input{font-size:16px}
  .status{padding:8px 16px;font-size:12.5px}
  .sum{padding:12px 16px;gap:16px}
  .sum .n{margin-left:0}
  .p-bd{padding:16px}
  .p-ft{padding:12px 16px;position:sticky;bottom:0;background:var(--paper)}
   .lst{overflow-x:hidden}
   .nv{min-height:44px}
   a.brand{min-height:44px;display:flex;align-items:center}
  .li{width:100%;max-width:100%;min-height:64px;display:flex;flex-direction:column;
   align-items:stretch;justify-content:center;gap:4px;padding:10px 16px;
   border:0;border-bottom:1px solid var(--line2);background:transparent;appearance:none;-webkit-appearance:none;text-align:left;cursor:pointer;
   overflow:hidden}
  .li .m-row{display:flex;align-items:center;gap:8px;min-width:0}
  .li .d{font-size:12.5px;color:var(--mut);white-space:nowrap;flex:0 0 auto}
  .li .m-cat{font-size:13px;font-weight:600;flex:0 1 auto;min-width:0;overflow:hidden;
   text-overflow:ellipsis;white-space:nowrap}
  .li .t{flex:1 1 auto;min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis;
   white-space:nowrap;font-size:14px;color:var(--ink);overflow-wrap:anywhere}
  .li .mobile-party .t{white-space:normal;overflow:visible;text-overflow:clip}
  .li .a{margin-left:auto;flex:0 0 auto;white-space:nowrap;font-size:15px;font-weight:600}
  .li .tag{flex:0 0 auto}
  .li[aria-selected="true"]{background:var(--sel);box-shadow:inset 2px 0 0 var(--grn)}
  .li.pend{white-space:normal;padding-top:12px;padding-bottom:4px}
  .lst form[data-js-move]{display:flex;gap:8px;align-items:center;padding:0 16px 12px;
   border-bottom:1px solid var(--line2);max-width:100%}
  .lst form[data-js-move] .psel{flex:1 1 0;min-width:0;margin-top:0}
  .lst form[data-js-move] .btn{flex:0 0 76px;min-width:76px}
  .lg{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;
   background:var(--bg);font-size:12px;font-weight:600;color:var(--mut);border-bottom:1px solid var(--line)}
}
"""

# Only three behaviours, all on top of the existing endpoints.
SCRIPT = """
(function(){
 var main=document.getElementById('main'), nav=document.getElementById('nav'),
     mask=document.getElementById('nav-mask');
 var stickyBar=main&&main.querySelector('.bar');
 if(stickyBar&&window.ResizeObserver){
  var syncStickyBarHeight=function(){
   main.style.setProperty('--mobile-bar-height',stickyBar.getBoundingClientRect().height+'px');
  };
  new ResizeObserver(syncStickyBarHeight).observe(stickyBar);
  syncStickyBarHeight();
 }
 function csrf(form){var el=form.querySelector("input[name='csrf']");return el?el.value:'';}
 function post(url,data){
  return fetch(url,{method:'POST',headers:{'Content-Type':'application/json',
   'X-CSRF-Token':csrf(document)},body:JSON.stringify(data)})
   .then(function(r){return r.json().then(function(j){return{ok:r.ok,body:j};});});
 }
 function say(el,text,bad){
  if(!el) return;
  el.textContent=text;
  el.className=bad?'f-msg err':'f-msg';
 }
function goBack(){location.href=main.dataset.base;}
  // ------------------------------------------- the panel's own state, read only
  function panel(){return document.getElementById('panel');}
  function panelForm(){var p=panel();return p?p.querySelector('form[data-js-save]'):null;}
  function panelRow(){var p=panel();return p?(p.getAttribute('data-row')||''):'';}
  // The rows that are on screen, in the order they are on screen. Both markups
  // are read — the desktop table's rows and the phone list's buttons — and a
  // layout only ever renders one of them, so this is a walk over what a reader
  // can see either way. A row inside a hidden section has no boxes at all and is
  // not walked past: the position beside the buttons counts real rows only.
  function visibleRowIds(){
   var out=[],rows=document.querySelectorAll('.tw tr[data-id],.lst .li[data-id]');
   for(var i=0;i<rows.length;i++){
    if(!rows[i].getClientRects().length) continue;
    out.push(rows[i].getAttribute('data-id'));
   }
   return out;
  }
  // The open row is in the address, so a refresh and a shared link both come back
  // to the same row. `replaceState` and not a navigation: the panel is already
  // open, and a history entry per row would make the browser's back button walk
  // through every row the reader looked at.
  function setRowParam(id){
   if(!window.history||!window.history.replaceState) return;
   var url=new URL(location.href);
   if(id) url.searchParams.set('row',id);
   else url.searchParams.delete('row');
   try{window.history.replaceState(null,'',url.toString());}catch(e){}
  }
  // Exactly one selected row, always, in whichever markup is on screen. The mark
  // is set from the panel's own row rather than added to whatever was clicked, so
  // a second click cannot leave two rows looking selected, and a live refresh
  // that replaced the list cannot leave none.
  function markSelection(){
   var cur=panelRow();
   var rows=document.querySelectorAll('.tw tr[data-id],.lst .li[data-id]');
   for(var i=0;i<rows.length;i++){
    if(rows[i].getAttribute('data-id')===cur) rows[i].setAttribute('aria-selected','true');
    else rows[i].removeAttribute('aria-selected');
   }
  }
  // Show the two walking buttons only when there is somewhere to walk, and say
  // which row of how many. Both come from the rows on screen, so they are absent
  // rather than wrong when the open row is not among them.
  function syncNav(){
   var prev=document.getElementById('p-prev'),next=document.getElementById('p-next'),
    count=document.getElementById('p-count');
   if(!prev||!next||!count||!panel()) return;
   var ids=visibleRowIds(),i=ids.indexOf(panelRow());
   if(i<0){
    prev.hidden=true;next.hidden=true;count.textContent='';return;
   }
   // A button with no row to walk to is not shown at all. One row of six is a
   // real position and is still said; the two ends of a one row list are the
   // same row, so offering them would be offering a move that cannot happen.
   prev.hidden=(i<=0);
   next.hidden=(i>=ids.length-1);
   count.textContent=(i+1)+' / '+ids.length;
  }
  var panelLoading=false;
  function openPanel(id){
   // The row that is already open needs no panel and no question: re-fetching it
   // would throw away what was typed for no gain.
   if(!id||id===panelRow()) return;
   if(!canLeavePanel()) return;
   panelLoading=true;
   var slot=document.getElementById('panel-slot');
   slot.inert=true;slot.setAttribute('aria-busy','true');
   var url=new URL(location.href); url.searchParams.set('row',id);
   fetch(url.toString(),{headers:{'X-Part':'panel'}})
    .then(function(r){if(!r.ok) throw new Error('PANEL_LOAD_FAILED');return r.text();})
    .then(function(html){
     var content=document.createElement('div');content.innerHTML=html;
     if(!content.querySelector('#panel')) throw new Error('PANEL_LOAD_FAILED');
     releasePanel();
     slot.innerHTML=html;
     markSelection();
     syncNav();
     // Focus the panel, not a field in it: a field that holds the keyboard stops
     // the cross-screen refresh from applying, and a reader who only opened a row
     // has not started editing one.
     var p=panel();
     if(p){try{p.focus({preventScroll:true});}catch(e){try{p.focus();}catch(e2){}}}
     setRowParam(id);
    }).catch(function(){
     say((panelForm()&&panelForm().querySelector('.f-msg'))||document.getElementById('status'),
      '거래를 불러오지 못했어요. 입력은 그대로 남아 있습니다. 다시 시도해 주세요',true);
    }).finally(function(){panelLoading=false;slot.inert=false;slot.removeAttribute('aria-busy');});
  }
  function closePanel(){
   if(!canLeavePanel()) return;
   releasePanel();
   goBack();
  }
  // Previous/next over the rows on screen. A step that would leave the list does
  // nothing, which is what the disabled button already says.
  function stepRow(delta){
   var ids=visibleRowIds(),i=ids.indexOf(panelRow());
   if(i<0) return;
   var target=ids[i+delta];
   if(!target) return;
   openPanel(target);
  }
  // The one guard every way out of the panel shares: the close button, Escape,
  // another row, and the previous/next buttons all pass through here. A save in
  // flight is not interrupted — the answer is not on screen yet — and a typed edit
  // is only dropped after the reader says so.
  function canLeavePanel(){
   if(panelLoading) return false;
   if(document.querySelector('form[data-saving="1"]')){
    var slot=(panelForm()&&panelForm().querySelector('.f-msg'))||
     document.getElementById('status');
    say(slot,'저장하는 중이에요. 저장이 끝난 뒤 이동해 주세요',false);
    return false;
   }
   var f=panelForm();
   if(f&&f.getAttribute('data-dirty')&&!window.confirm(
    '저장하지 않은 변경이 있어요. 저장하지 않고 이동할까요?')) return false;
   return true;
  }
  // Leaving is a decision, so the dirty mark goes with it and a change that was
  // held back for this panel is asked for again straight away.
  function releasePanel(){
   var f=panelForm();
   if(f) f.removeAttribute('data-dirty');
   reportUnsaved();
   window.dispatchEvent(new Event('ledger:saved'));
  }
 function refreshSummary(){
  var url=new URL(location.href);
  fetch(url.toString()+'&part=summary',{headers:{'X-Part':'summary'}})
   .then(function(r){return r.text();})
   .then(function(html){document.getElementById('sum').outerHTML=html;});
 }
document.addEventListener('click',function(e){
   if(e.target.closest('#p-cancel')&&document.querySelector('form[data-saving="1"]')){
    e.preventDefault();canLeavePanel();return;
   }
   if(e.target.id==='p-close'){e.preventDefault();closePanel();return;}
   // The two walking buttons live inside the save form, so they are answered
   // before the form guard below would swallow them.
   if(e.target.closest('#p-prev')){e.preventDefault();stepRow(-1);return;}
   if(e.target.closest('#p-next')){e.preventDefault();stepRow(1);return;}
   // The chrome buttons come first. The trip button sits inside the search form
   // now, so the form guard below would otherwise swallow it.
  if(e.target.closest('#btn-menu')){
   var open=nav.classList.toggle('open'); mask.hidden=!open;
   e.target.setAttribute('aria-expanded',open?'true':'false'); return;
  }
  if(e.target===mask){nav.classList.remove('open');mask.hidden=true;return;}
  // A control inside a row form belongs to that form. Opening the panel there
  // would swallow the click and the control would do nothing.
  if(e.target.closest('form')) return;
  var row=e.target.closest('tr[data-id]');
  if(row){e.preventDefault();openPanel(row.dataset.id);return;}
  var item=e.target.closest('.li[data-id]');
  if(item){e.preventDefault();openPanel(item.dataset.id);return;}
 });
 document.addEventListener('submit',function(e){
  var form=e.target;
  if(!form.matches('[data-js-save]')&&!form.matches('[data-js-move]')) return;
  e.preventDefault();
  var isSave=!!form.matches('[data-js-save]');
  var slot=isSave?form.closest('.panel').querySelector('.f-msg')
                :document.getElementById('status');
  var payload={csrf:csrf(form)};
  Array.prototype.forEach.call(form.elements,function(el){
   if(!el.name||el.name==='csrf'||el.disabled||el.readOnly) return;
   if(el.type==='checkbox'||el.type==='radio'){ if(el.checked) payload[el.name]=el.value; return; }
   payload[el.name]=el.value;
  });
   say(slot,isSave?'저장하는 중입니다':'옮기는 중입니다',false);
   // A save in flight is a reason not to swap the screen underneath it. The
   // cross-screen refresh reads this same mark, so the two behaviours cannot
   // disagree about whether an edit is still happening.
   form.setAttribute('data-saving','1');
   post(form.getAttribute('action'),payload).then(function(res){
    form.removeAttribute('data-saving');
    var body=res.body||{};
    if(res.ok&&body.outcome){
    if(isSave){
     var rev=form.querySelector("input[name='expected_revision']");
     if(rev&&body.revision) rev.value=body.revision;
     // A second edit from the same panel must not reuse the first request id,
     // or the store would answer REQUEST_ID_REUSED instead of saving.
     var req=form.querySelector("input[name='client_request_id']");
     if(req) req.value=(window.crypto&&window.crypto.randomUUID)
      ?window.crypto.randomUUID()
      :String(Date.now())+'-'+String(Math.random()).slice(2);
     var open=document.getElementById('rule-open');
     if(body.learning_case_id){
      if(open) open.hidden=false;
      else{
       var made=document.createElement('a');
       made.id='rule-open';
       made.textContent='규칙 대화 열기';
       var box=document.querySelector('.p-links');
       if(box){box.appendChild(document.createTextNode(' · '));box.appendChild(made);}
      }
      var link=document.getElementById('rule-open');
      if(link) link.href='/rules?case='+encodeURIComponent(body.learning_case_id);
     }
      say(slot,'저장했습니다 (revision '+body.revision+')',false);
      clearDirty(form);
      // The row's own identity did not change, so the position beside the walking
      // buttons and the one selected row are read again from the live DOM.
      markSelection();
      syncNav();
     }else{
     say(slot,'옮겼습니다. 목록과 합계가 갱신되었어요',false);
    }
    if(isSave){refreshSummary();}
else{
      var next=new URL(location.href);
      next.searchParams.set('msg','옮겼습니다. 목록과 합계가 갱신되었어요');
      // The row is no longer in the list this screen was showing, so the address
      // stops naming it. Leaving `row` behind would reopen a panel for a row that
      // is not in the table the reader is looking at.
      next.searchParams.delete('row');
      location.href=next.toString();
     }
    return;
   }
    say(slot,(body.code||'ERROR')+': '+(body.message||'저장하지 못했어요'),true);
    flagField(form,body,slot);
   }).catch(function(){
    form.removeAttribute('data-saving');
    say(slot,'요청을 보내지 못했어요. 연결을 확인해 주세요',true);
   }).then(function(){
    // A save that finished, succeeded or not, is the moment a deferred
    // cross-screen change is wanted. The refresh listens for this and asks
    // again immediately rather than waiting out its interval.
    window.dispatchEvent(new Event('ledger:saved'));
   });
  });

  // ---------------------------------------------------- keyboard (contract 12.3)
  //
  // Enter alone must never save a row quietly, and it must not steal the
  // newline in a note. Ctrl+Enter is the explicit save and it is printed on
  // the button. Escape cancels the open edit without touching anything that
  // was already saved, asks before dropping unsaved input, and puts focus
  // back on the row the panel came from.
  function hasUnsaved(form){
   var base=form.querySelector("input[name='expected_revision']");
   if(!base) return false;
   var start=form.getAttribute('data-dirty-from')||'';
   var dirty=false;
   Array.prototype.forEach.call(form.elements,function(el){
    if(!el.name||el.name==='csrf'||el.name==='client_request_id'
     ||el.name==='expected_revision'||el.name==='return_to') return;
    if(el.type==='checkbox'||el.type==='radio'){
     if(String(el.checked)!==String(el.getAttribute('data-was')==='1')) dirty=true;
     return;
    }
    if(!start&&el.value!==''&&el.value!==el.getAttribute('placeholder')) {}
    if(el.value!==(el.defaultValue||'')) dirty=true;
   });
   return dirty;
  }
  function markDirty(form){
   if(form.getAttribute('data-dirty')) return;
   form.setAttribute('data-dirty','1');
   reportUnsaved();
  }
  function clearDirty(form){form.removeAttribute('data-dirty');reportUnsaved();}
  // APP_SPEC 4.1: the global top area shows the unsaved row count. It is
  // derived from the same dirty marks the Escape guard uses, so the number
  // and the warning cannot disagree.
  function reportUnsaved(){
   var slot=document.getElementById('unsaved-count');
   if(!slot) return;
   var n=document.querySelectorAll('form[data-dirty="1"]').length;
   slot.hidden=!n;
   slot.textContent=n?(n+'건 저장되지 않은 변경'):'저장되지 않은 변경 없음';
  }
  // 4.1 also asks that leaving the page with an unsaved edit confirm first.
  window.addEventListener('beforeunload',function(ev){
   if(!document.querySelector('form[data-dirty="1"]')) return;
   ev.preventDefault();ev.returnValue='';
  });
  reportUnsaved();

  // A refused field is named next to the input and focused first, so the
  // error is not communicated by colour alone.
  function flagField(form,body,slot){
   var field=body&&(body.field||body.field_name);
   if(!field) return;
   var input=form.querySelector("[name='"+field+"']");
   if(!input) return;
   input.classList.add('f-err');
   input.setAttribute('aria-invalid','true');
   var flag=document.createElement('span');
   flag.className='f-flag';
   flag.id='f-flag';
   flag.textContent=(body.message||'이 칸을 확인해 주세요');
   if(input.parentNode&&!input.parentNode.querySelector('.f-flag')){
    input.parentNode.appendChild(flag);
   }
   try{input.focus();input.select&&input.select();}catch(e){}
  }
  function clearFlags(form){
   Array.prototype.forEach.call(form.querySelectorAll('.f-err'),function(el){
    el.classList.remove('f-err');el.removeAttribute('aria-invalid');
   });
   Array.prototype.forEach.call(form.querySelectorAll('.f-flag'),function(el){
    el.parentNode.removeChild(el);
   });
  }

document.addEventListener('keydown',function(e){
    // A row is focusable, so it has to answer the keyboard the way a button
    // does. Enter and Space open it; without this a keyboard reader could focus
    // a row and do nothing with it.
    if(e.key==='Enter'||e.key===' '||e.key==='Spacebar'){
     var tr=e.target.closest&&e.target.closest('tr[data-id]');
     if(tr&&!(e.target.closest&&e.target.closest('button,select,input,textarea,a'))){
      e.preventDefault();
      openPanel(tr.getAttribute('data-id'));
      return;
     }
    }
    var form=e.target.closest&&e.target.closest('form[data-js-save]');
    // Ctrl+Enter is the one key that saves, from anywhere in the panel form.
    if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&form){
     e.preventDefault();
     if(typeof form.requestSubmit==='function') form.requestSubmit();
     else form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));
     return;
    }
    if(e.key==='Enter'&&form&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
     // A textarea keeps its newline. A single-line field is not a save: it
     // just does nothing, so a stray Enter cannot write a row.
     var tag=(e.target.tagName||'').toLowerCase();
     if(tag==='textarea') return;
     if(e.target.type==='button'||e.target.type==='submit') return;
     e.preventDefault();
     return;
    }
    if(e.key==='Escape'){
     if(!panel()) return;
     // The same guard the close button and the row walk use: a refused answer
     // leaves the panel and the draft exactly as they were.
     if(!canLeavePanel()) return;
     releasePanel();
     // Return focus to the row the panel was opened from.
     var opener=document.querySelector('tr[data-id][aria-selected="true"]');
     if(opener){
      var target=opener.querySelector('button,td,a')||opener;
      try{target.focus();}catch(e){}
     }
     goBack();
    }
   });
  // A finished save, and a row list that another screen replaced, both mean the
  // selection and the position beside the walking buttons have to be read again.
  window.addEventListener('ledger:saved',function(){markSelection();syncNav();});
  var region=document.getElementById('live-rows');
  if(region&&window.MutationObserver){
   new MutationObserver(function(){markSelection();syncNav();})
    .observe(region,{childList:true,subtree:true});
  }
  // Any change marks the panel dirty so Escape knows to ask.
  document.addEventListener('input',function(e){
   var form=e.target.closest&&e.target.closest('form[data-js-save]');
   if(form) markDirty(form);
  });
  // A finished save leaves nothing unsaved.
  document.addEventListener('submit',function(e){
   var form=e.target;
   if(form.matches&&form.matches('form[data-js-save]')) clearFlags(form);
  },true);
 })();
 """


# ----------------------------------------------------------------- fragments
def _money(value) -> str:
    return MONEY.format(int(value or 0))


def work_menu_html() -> str:
    """Owner work entry points for the home body, with honest states.

    This lives in the home body only. The sidebar carries the stable primary
    menu (including the single 미배정 지출 entry in the trip region), so this
    menu must not repeat those links. 미배정 지출 is intentionally absent
    here: its one entry point is the sidebar region.
    """
    if board.current_role() != 'owner':
        return ''
    from . import google_ledger_page, receipt_review, ui_icons

    def action(icon, title, note, href=''):
        if not href:
            return ''
        tag = 'a' if href else 'div'
        link = f" href='{board.esc(href)}'" if href else ''
        return (f"<{tag} class='work-action'{link}>{ui_icons.icon(icon)}"
                f"<span><strong>{title}</strong>"
                f"</span></{tag}>")

    actions = action('upload', '지출 정리', '카드 파일 추가 · 미배정 지출 정리 · 오분류 수정 · 전체 카드 검색', '/import')
    actions += action('list', 'OTA 내역', '예약 조회 · 여행 미배정 확인 · 검색 · 이용월 조회', '/ota')
    if receipt_review.enabled():
        actions += action('receipt', '영수증 처리', '이미지 업로드 · 수동 입력 · 복사', '/receipts')
    else:
        actions += action('receipt', '영수증 처리 · 설정 필요', '비공개 저장 위치를 연결하면 수동 입력을 사용할 수 있어요')
    return ("<section class='work-menu' id='work-menu' aria-label='지금 할 업무'>"
            f"<h2>지금 할 업무</h2><nav class='work-actions'>{actions}</nav></section>")


def _nav_html(tab_id: str, query: str, kind: str = "", archived: str = "") -> str:
    """The whole trip rail: the brand link, the search box, the region, the footer.

    The search box sits outside the swappable region on purpose. It holds what the
    user typed, and a refresh that replaced it would take the caret and the text
    with it.
    """
    from . import ui_icons as _icons
    if board.current_role() == 'owner':
        from . import flight_passenger_page, receipt_review
        primary = ("<nav class='site-links' aria-label='주요 메뉴'>"
                   f"<a href='/board'>{_icons.icon('book-open', 18)}<span class='nm'>여행 장부</span></a>"
                   f"<a href='/import'>{_icons.icon('upload', 18)}<span class='nm'>지출 정리</span></a>"
                   f"<a href='/ota'>{_icons.icon('list', 18)}<span class='nm'>OTA 내역</span></a>")
        if receipt_review.enabled():
            primary += (f"<a href='/receipts'>{_icons.icon('receipt', 18)}"
                        "<span class='nm'>영수증 처리</span></a>")
        management = ("</nav><h2 class='nav-sec'>관리</h2>"
                      "<nav class='site-links' aria-label='관리 메뉴'>"
                      f"<a href='/trips'>{_icons.icon('map', 18)}<span class='nm'>여행 관리</span></a>"
                      f"<a href='/reserve-links'>{_icons.icon('link', 18)}<span class='nm'>예약 명단·여행 연결</span></a>")
        if flight_passenger_page.enabled():
            management += (f"<a href='/flight-passengers'>{_icons.icon('users', 18)}"
                           "<span class='nm'>항공권 참가자 연결</span></a>")
        primary += (management
                    + f"<a href='/access/admin'>{_icons.icon('users', 18)}<span class='nm'>계정·권한 관리</span></a>"
                    + "</nav>")
    else:
        primary = ("<nav class='site-links' aria-label='주요 메뉴'>"
                   f"<a href='/board'>{_icons.icon('book-open', 18)}<span class='nm'>여행 장부</span></a>")
        primary += '</nav>'
    search = (
        "<form class='nav-q' method='get' action='/board'>"
        f"<input type='hidden' name='tab' value='{board.esc(tab_id)}'>"
        f"{f'<input type=hidden name=kind value={board.esc(kind)}>' if kind else ''}"
        "<label class='sr' for='tripq'>여행 검색</label>"
        f"<input id='tripq' name='q' type='search' placeholder='여행 이름·코드'"
        f" value='{board.esc(query)}' autocomplete='off'></form>")
    return (
        "<aside class='nav' id='nav' aria-label='여행 목록'>"
        "<div class='nav-hd'><a class='brand brand-link' href='/' aria-label='숲길여행 회계 홈으로 이동'><img src='/assets/brand/wallet-favicon-v2.png' alt='' width='20' height='20'>숲길여행 회계</a></div>"
        f"{primary}{search}"
        + nav_region(tab_id, query, kind, archived)
        + "</aside>"
        "<div class='nav-mask' id='nav-mask' hidden></div>")


_CURRENT_YEAR = 2026
_FOCUS_ON_OPEN = ("var d=this.parentNode;setTimeout(function(){if(d.open){"
                  "var t=d.querySelector('.prev-q>summary, a');if(t)t.focus()}},0)")


def _quarter_of(trip):
    try:
        day = date.fromisoformat(trip.get("starts_on") or "")
    except (TypeError, ValueError):
        return None
    return day.year, (day.month - 1) // 3 + 1


def _quarter_groups(trips):
    """The quarters the previous trips fall in, plus the 1st and 2nd quarter of the current year."""
    found = {_quarter_of(t) for t in trips} - {None}
    return sorted(found | {(_CURRENT_YEAR, 1), (_CURRENT_YEAR, 2)})


def _nav_region_inner(tab_id: str, query: str, kind: str = "",
                      archived: str = "") -> str:
    """The trip rail region's contents, without the region's own element.

    One renderer for this markup. The page puts it inside `nav_region`, and a live
    fragment carries the same string, so a refreshed rail and a freshly loaded one
    cannot disagree about the selected trip, the archived drawer, or a total.
    """
    state = state_query(tab_id, query, kind, archived)
    drawer_open = archived in ("1", "open", "true")

    def entry(label, href, count, current, warn=False, archived_row=False):
        cls = "nv sel" if current else ("nv nv-arch" if archived_row else "nv")
        badge = (f"<span class='ct{' warn' if warn else ''}'>{count}</span>"
                 if count is not None else "")
        return (f"<li><a class='{cls}' href='{href}'"
                f"{' aria-pressed=\"true\"' if current else ''}>"
                f"<span class='nm'>{label}</span>{badge}</a></li>")

    sections = []
    trips = board.live_trips(include_archived=True)
    # A viewer's rail lists only the trips its allowlist names. The rail is
    # rendered by the shared chrome, so without this the `+ 탭 추가` control was
    # correctly hidden from a viewer while the trip names beside it were not:
    # a trip the viewer may not read was still named, and its total was still
    # shown. The role is decided on the server for this request, so the filter
    # is the server's own answer and not anything the request asked for.
    if board.current_role() == "viewer":
        allowed = board.viewer_visible_tabs(board.current_request_session())
        trips = [t for t in trips if t["tab_id"] in allowed]
    # Display grouping only: never archive or rewrite a trip or its ledger.
    def previous_trip(trip):
        try:
            return date.fromisoformat(trip.get("starts_on") or "") <= date(2026, 6, 25)
        except (TypeError, ValueError):
            return False

    previous_rows = [t for t in trips if not t.get("deleted") and previous_trip(t)]
    active = [t for t in trips if not t.get("archived") and not t.get("deleted")
              and not previous_trip(t)]
    archived_rows = [t for t in trips if t.get("archived") and not t.get("deleted")
                     and not previous_trip(t)]
    def short_date(value):
        parts = str(value or '').split('-')
        if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) == 4:
            return f"{parts[1]}.{parts[2]}"
        return str(value or '')

    def trip_entry(trip):
        # 금액 badge를 표시하지 않는다. 수입 합계는 장부 화면의 합계 영역이
        # 맡고, 목록에는 일정과 이동 상태만 둔다. Google 집계 금액과의 혼동을
        # 막기 위한 표시 변경이며 집계 로직은 그대로 둔다.
        start, end = trip.get("starts_on") or "", trip.get("ends_on") or ""
        if start and end:
            dates = f"{short_date(start)}~{short_date(end)}"
        else:
            dates = short_date(start or end) or None
        return entry(
            board.esc(trip["display_key"]),
            f"/board?{state_query(trip['tab_id'], query, kind, archived)}",
            dates, trip["tab_id"] == tab_id)

    listed = []
    for trip in active:
        if query and query not in (trip["display_key"] + trip["destination"]):
            continue
        listed.append(trip_entry(trip))
    if board.current_role() == "owner":
        from app import quarter_tab
        for quarter in (3, 4):
            tab = quarter_tab.tab_id_for(_CURRENT_YEAR, quarter)
            listed.append(entry(f"{quarter}분기 기타비용", "/board?" + state_query(tab, query, kind, archived),
                                None, tab_id == tab))
    sections.append(("<h2 class='nav-sec'>여행 목록</h2>",
                     f"<ul class='nav-list' id='trips'>{''.join(listed) or '<li class=\"muted\" style=\"padding:6px 8px\">여행이 없어요</li>'}</ul>"))
    # 미배정 지출은 지출 정리(/import) 맨 위에서 처리한다. 여행 레일에는 따로 두지 않는다.
    arch_head = ""
    if board.current_role() == 'owner':
        sections.append(("<h2 class='nav-sec'>환불</h2>", "<ul class='nav-list'>" + entry(
            f"{ui_icons.icon('rotate-ccw')}환불", f"/board?{state_query('refunds')}",
            None, tab_id == 'refunds') + "</ul>"))
    if archived_rows:
        toggle_state = state_query(tab_id, query, kind, "" if drawer_open else "1")
        arch_head = (
            "<h2 class='nav-sec'>보관 목록</h2>"
            "<a class='nv nav-toggle' id='arch-toggle'"
            f" href='/board?{board.esc(toggle_state)}'"
            f" aria-expanded='{'true' if drawer_open else 'false'}'"
            " aria-controls='archived'>"
            f"<span class='nm'>보관 {len(archived_rows)}개</span>"
            f"<span class='ct'>{'접기' if drawer_open else '펼치기'}</span></a>")
    if archived_rows and drawer_open:
        rows = []
        for trip in archived_rows:
            href = f"/board?{state_query(trip['tab_id'], query, kind, archived)}"
            view = (
                f"<a class='btn arch-view' href='{href}'>보기</a>")
            restore = (
                "<form method='post' class='arch-restore' "
                f"action='/api/trips/{board.esc(trip['tab_id'])}/meta'>"
                f"<input type='hidden' name='csrf' value='{board.CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{trip.get('revision', 1)}'>"
                "<input type='hidden' name='client_request_id' value='"
                f"{uuid.uuid4().hex}'>"
                "<input type='hidden' name='archived' value='0'>"
                "<input type='hidden' name='return_to' value='"
                f"/board?{board.esc(state_query(tab_id, query, kind, archived))}'>"
                "<button class='btn' type='submit'>복원</button></form>")
            rows.append(
                "<li class='arch-row'>"
                f"<a class='nv nv-arch' href='{href}'>"
                f"<span class='nm'>{board.esc(trip['display_key'])}</span></a>"
                f"{view}{restore}</li>")
        arch_head += f"<ul class='nav-list' id='archived'>{''.join(rows)}</ul>"
    previous = ""
    matching_previous = [t for t in previous_rows
                         if not query or query in (t["display_key"] + t["destination"])]
    from app import quarter_tab
    show_quarters = board.current_role() == "owner"
    if matching_previous or show_quarters:
        # Default collapsed: the server never auto-opens for a selected trip or
        # a search. The user expands with one click (native details/summary).
        # Each quarter opens with the list, and focus moves into a group the
        # user has just opened, only after that user action.
        store = board._active_store()
        quarters = _quarter_groups(matching_previous)
        if show_quarters:
            quarters = sorted(set(quarters) | {(_CURRENT_YEAR, n) for n in (1, 2)})
        groups = []
        for year, quarter in quarters:
            members = [t for t in matching_previous if _quarter_of(t) == (year, quarter)]
            label = f"{quarter}분기" if year == _CURRENT_YEAR else f"{year}년 {quarter}분기"
            cost = ""
            if show_quarters and year == _CURRENT_YEAR and quarter <= 2:
                tab = quarter_tab.tab_id_for(year, quarter)
                count = 0  # nothing waits for a person on a quarter tab
                cost = entry(f"{quarter}분기 기타비용", "/board?" + state_query(tab, query, kind, archived),
                             count or None, tab_id == tab)
            rows = cost + ''.join(trip_entry(t) for t in members)
            body = ('<ul class="nav-list">' + rows + '</ul>' if rows
                    else "<p class='nav-sec'>여행 없음</p>")
            groups.append(
                "<details class='prev-q' open>"
                f"<summary class='nv' onclick=\"{_FOCUS_ON_OPEN}\"><span aria-hidden='true'>▸</span>"
                f"<span class='nm'>{label}</span><span class='ct'>{len(members)}개</span></summary>"
                f"{body}</details>")
        previous = (
            '<details id="previous-trips">'
            f"<summary class='nv' onclick=\"{_FOCUS_ON_OPEN}\"><span aria-hidden='true'>▸</span><span class='nm'>이전 여행</span>"
            f'<span class="ct">{len(matching_previous)}개</span></summary>'
            '<p class="nav-sec">2026년 6월 25일까지 여행</p>'
            + ''.join(groups) + '</details>')
    return "".join(head + body for head, body in sections) + arch_head + previous


def nav_region(tab_id: str, query: str = "", kind: str = "",
               archived: str = "") -> str:
    """The trip rail's own element: the one region a live refresh replaces.

    This is the single renderer for that region, and the full page embeds exactly
    what this returns. The alternative — rendering the whole rail and slicing the
    region back out of the string — is how a fragment ends up carrying the sidebar
    footer and the mask element that sit after it, which then arrive as a second
    `nav-mask` and a stray footer on every refresh.

    It returns the region's *outer* element, so a caller that only wants the inner
    markup has to say so rather than guess where the region ended.
    """
    return (f"<div id='live-nav'>{_nav_region_inner(tab_id, query, kind, archived)}"
            "</div>")


def nav_part(tab_id: str, query: str = "", kind: str = "",
             archived: str = "") -> str:
    """The swappable part of the trip rail, for a live refresh.

    The inner markup only, without the region's own element: the live sync adds
    that wrapper itself, so a bundle written here and a page rendered here cannot
    end up with two elements carrying the same id.
    """
    if _STORE_missing():
        return ""
    return _nav_region_inner(tab_id, query, kind, archived)


def _head_html(trip) -> str:
    from . import ui_icons as _icons
    if trip is None:
        title, period, meta = "여행을 선택해 주세요", "", ""
    elif trip.get("is_unclassified"):
        title = "분류대기"
        period = "여행을 정하지 않은 내역이에요"
        meta = "이 목록을 정리하면 여행 합계가 함께 갱신돼요"
    else:
        title = board.esc(trip["display_key"])
        period = f"{_icons.icon('calendar-days')}<span class='tnum'>{board.esc(trip['starts_on'])}~{board.esc(trip['ends_on'])}</span>"
        meta = (f"<span>작성일 <b>{board.esc(trip.get('prepared_on') or '-')}</b></span>"
                f"<span>{_icons.icon('users')}담당자 <b>{board.esc(trip.get('prepared_by_name') or '-')}</b></span>"
                f""
                f"<span><a class='btn' href='/trips'>{_icons.icon('map')}여행 관리</a></span>")
    return (
        "<div class='page-hd'><div>"
        f"<h1>{title}<span class='synth'>{board.data_status_mark()}</span></h1>"
        f"<p class='period'>{period}</p>"
        f"<p class='meta'>{meta}</p></div>"
        "<div class='act'>"
        + _reserve_link_link_html()
        + _review_link_html()
        + f"<a class='btn' href='/import'>{_icons.icon('upload')}카드 가져오기</a>"
        f"<a class='btn primary' href='/export'>{_icons.icon('save')}XLSX 출력</a>"
        "</div></div>")


def _reserve_link_link_html() -> str:
    """The link to the reservation-event linking screen, for an owner only.

    The screen is reachable from the ledger header so that a feature does not
    need its address typed in. Two conditions decide whether the link is drawn,
    and each exists for a reason:

    * The role. A viewer is refused the route itself, and a link a viewer can
      see but cannot open is worse than no link at all. The route decides the
      role again on every request, so this markup is a convenience and never the
      decision.
    * Not the configuration. This is the one place where the two header links
      differ on purpose. The review link is hidden when no review is configured,
      because opening it would show nothing useful. The linking screen instead
      answers "설정이 필요해요" when the source is not configured, and that answer
      is the reason to show the link: hiding it would leave an installation with
      no configured source unable to find out that one is needed. Hiding it here
      would make the configuration-required state unreachable except by knowing
      the address, which is the same gap this link exists to close.

    Nothing here reads the roster, and nothing searches for one.
    """
    if board.current_role() != "owner":
        return ""
    from . import ui_icons as _icons
    return ("<a class='btn' id='reserve-link' href='/reserve-links' aria-label='예약 명단·여행 연결'>"
            f"{_icons.icon('link')}예약 연결</a>")


def _review_link_html() -> str:
    """The link to the actual-source comparison, when one is configured.

    Rendered only when a review is configured, so an installation without one
    has no dead link. The owner page is the only place it appears: a viewer is
    refused the route itself, and a link they can see but cannot open is worse
    than no link. The route decides the role again on every request, so this
    markup is a convenience and never the decision.
    """
    from . import real_review
    from . import ui_icons as _icons

    if real_review.active_service() is None:
        return ""
    return (f"<a class='btn' id='review-link' href='/review'>{_icons.icon('search')}실제 자료 검토</a>")


def _source_sheet_name(locator: str) -> str:
    """The sheet an explicit source reference names, or "" when it names none.

    A locator looks like `시트명!$A$5|$B$5 (row 5)`. Only the part before the
    first `!` is the sheet, and only a locator that has one is used: matching a
    trip to a sheet by anything else — a prefix, a date, a settlement day, a
    "looks like the same trip" judgement — is a guess, and a guessed trip's
    source rows would sit under the wrong name.
    """
    text = str(locator or "")
    if "!" not in text:
        return ""
    return text.split("!", 1)[0].strip()


def _saved_review_choices(service) -> dict:
    """The review screen's saved decisions, read only, or {} when unavailable.

    Read for display only. Nothing here writes, and no choice is created,
    cleared or changed — a screen that renders state must not be able to move
    it. A read that fails leaves the original per-row decision visible, so the
    screen degrades to what the snapshot itself carried rather than to nothing.
    """
    try:
        state = service.state()
    except Exception:
        return {}
    choices = (state or {}).get("choices")
    return choices if isinstance(choices, dict) else {}


def _source_rows_for_trip(trip) -> list:
    """The source rows whose sheet is exactly this trip's display key.

    An exact string equality, once. Nothing here infers: no dates, no amounts,
    no ordering, no "only one trip could match". A trip with no sheet of its own
    gets nothing, which is the honest answer.
    """
    if not trip:
        return []
    if board.current_role() != "owner":
        return []
    wanted = str(trip.get("display_key") or "")
    if not wanted:
        return []
    try:
        from . import real_review

        service = real_review.active_service()
        if service is None:
            return []
        model = service.model()
        saved = _saved_review_choices(service)
    except Exception:
        # An unbound, unreadable or refused service leaves the ledger exactly as
        # it was. A screen that failed to read the source must not also fail to
        # show the ledger.
        return []
    rows = []
    for row in (model or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        source = row.get("source")
        if not isinstance(source, dict):
            continue
        if _source_sheet_name(source.get("sourceLocator")) != wanted:
            continue
        # The snapshot's own decision, and a saved choice when there is one. A
        # blank decision stays blank: it is never promoted to something.
        decision = saved.get(row.get("ref"))
        if not isinstance(decision, str) or not decision.strip():
            decision = str(row.get("decision") or "")
        rows.append({"source": source, "decision": decision})
    return rows


def _source_preview_html(trip) -> str:
    """The trip's actual source rows, shown beside the ledger, read only.

    The reason this exists: a trip with nothing in the ledger shows an empty
    ledger and no way to tell "nothing happened" from "nothing has been entered
    yet". The source is what tells those apart.

    Three things it must not do:

    * **Not be a ledger total.** It is headed as the actual source, before it
      reaches the ledger, and it sits outside `#live-sum`, so the saved totals
      above are untouched and cannot be read as including it.
    * **Not decide anything.** No approval, no selection, no write. The only
      control is a link to the comparison screen, which is where decisions are
      made.
    * **Not guess the trip.** Only a sheet whose name is exactly this trip's
      display key is shown.
    """
    from . import card_flow
    if card_flow.enabled():
        return ""
    rows = _source_rows_for_trip(trip)
    sheet = _source_sheet_name(
        (rows[0]["source"].get("sourceLocator") if rows else "")) or (
            str(trip.get("display_key") or "") if rows else "")
    if not rows:
        return ""
    items = []
    for entry in rows:
        source = entry["source"]
        cells = source.get("fieldcells") or []
        # Built raw and escaped once, at the end. Escaping here and then again
        # in the fallback below would turn a literal `&` into `&amp;amp;` on
        # screen, which is a worse answer than the raw text it replaced.
        labelled = " · ".join(
            f"{cell.get('label') or ''} {cell.get('value') or ''}"
            for cell in cells
            if isinstance(cell, dict) and str(cell.get("label") or "").strip())
        decision = entry["decision"]
        decision_text = ("미검토" if not decision.strip() else decision)
        # Which block this row is. A row from before the kind existed has none,
        # and reads as an expense row so an existing installation is unchanged.
        block_kind = str(source.get("block_kind") or "expense")
        if block_kind not in ("income", "expense", "unknown"):
            block_kind = "expense"
        income = block_kind == "income"
        if income:
            decision_text = "입금 원본 조회"
        badge = {"income": "입금",
                 "expense": "지출"}.get(block_kind, "구분 확인 필요")
        evidence = source.get("evidence_status") == "available"
        content = str(source.get("description") or labelled or "-")
        if income:
            components = source.get("income_components") or {}
            content = " · ".join(
                f"{label} {components[label]}원"
                for label in ("예약금", "잔금", "추가금")
                if str(components.get(label) or "").strip()) or "-"
        items.append(
            f"<li class='src-row' data-block-kind='{board.esc(block_kind)}'>"
            f"<p class='src-line'><span>종류</span>"
            f"<b>{board.esc(badge)}</b></p>"
            + ((f"<p class='src-line'><span>이름</span><b>"
                f"{board.esc(source.get('customer_name') or '-')}</b></p>"
                f"<p class='src-line'><span>닉네임</span><b>"
                f"{board.esc(source.get('nickname') or '-')}</b></p>")
               if income else "")
            + f"<p class='src-line'><span>날짜</span>"
            f"<b>{board.esc(source.get('date') or '-')}</b></p>"
            f"<p class='src-line'><span>금액</span>"
            f"<b class='tnum'>{board.esc(source.get('amount') or '-')}</b></p>"
            + (f"<p class='src-line'><span>내용</span><b>"
               f"{board.esc(content)}</b></p>" if content != "-" else "")
            + "<p class='src-line'><span>원본 위치</span>"
              f"<code>{board.esc(source.get('sourceLocator') or '-')}</code></p>"
            + f"<p class='src-line'><span>검토 상태</span>"
              f"<b>{board.esc(decision_text)}</b>"
            + ("" if evidence else
               " <span class='muted'>· 원본 머리글 확인 필요</span>")
            + "</p></li>")
    # Percent-encoded, not just escaped. A sheet name is free text and can hold
    # `&`, `+`, `#` or a space, all of which mean something else inside a query
    # string; escaping alone would produce a link that opens the wrong search.
    review_href = "/review?q=" + urllib.parse.quote(sheet, safe="")
    # The button sits with the heading rather than after the rows. A trip with
    # dozens of source rows pushes a trailing link far past the fold, and the
    # control a reader wants first becomes the one they have to scroll to.
    return (
        f"<section class='src-preview' id='src-preview'>"
        f"<div class='src-hd'><h2>실제 원천 자료 · 입금과 지출</h2>"
        f"<a class='btn' id='src-review-link' href='{board.esc(review_href)}'>"
        f"{ui_icons.icon('search')}실제 자료 검토</a></div>"
        f"<p class='muted'>원천 시트 <code>{board.esc(sheet)}</code> 의 "
        f"{len(items)}행이에요. 원천 자료입니다. 저장된 장부 합계와 별도로 "
        f"표시합니다. 검토에서 차이를 확인하세요. 여기서 결정하지 않아요.</p>"
        f"<ul class='src-list'>{''.join(items)}</ul>"
        f"</section>")


def _bar_html(query: str, kind: str, tab_id: str, archived: str = "") -> str:
    # One GET form owns the search and the filter, so submitting, refreshing and
    # going back all land on the same URL state.
    from . import ui_icons as _icons
    return (
        "<form class='bar' method='get' action='/board' id='q-form'>"
        f"<input type='hidden' name='tab' value='{board.esc(tab_id)}'>"
        f"{f'<input type=hidden name=arch value={board.esc(archived)}>' if archived else ''}"
        "<button class='icon' id='btn-menu' type='button' aria-label='전체 메뉴 열기'"
        f" aria-controls='nav' aria-expanded='false'>{_icons.icon('menu')}</button>"
        "<label class='sr' for='q'>거래 검색</label>"
        "<input id='q' name='q' type='search' placeholder='용도·내용·메모·예약번호 검색'"
        f" value='{board.esc(query)}' autocomplete='off'>"
        "<label class='sr' for='kind'>구분 필터</label>"
        "<select id='kind' name='kind' onchange='this.form.submit()'>"
        f"<option value=''>전체</option><option value='in'{' selected' if kind == 'in' else ''}>수입만</option>"
        f"<option value='ex'{' selected' if kind == 'ex' else ''}>지출만</option></select>"
        f"<button class='btn' type='submit' id='q-go'>{_icons.icon('search')}검색</button>"
        + (f"<a class='btn' id='q-clear' href='/board?{state_query(tab_id)}'>{_icons.icon('rotate-ccw')}지우기</a>"
           if (query or kind) else "")
        + "</form>")


def _summary_html(incomes, expenses, *, filtered=None, whole=None, recorded_income_count=None) -> str:
    """The totals bar.

    DETAILED 12.2: with a filter on, the whole total and the result total get
    separate names, and the whole total is never quietly replaced by the result.
    `filtered` is (income, expense, count_income, count_expense) for the rows
    the filter left visible; `whole` is the same for the unfiltered tab.
    """
    income = sum(board._shown_amount(r) for r in incomes)
    expense = sum(board._shown_amount(r) for r in expenses)
    scope = "<span class='scope'>기록된 거래</span>"
    note = ""
    if not incomes and recorded_income_count in (0, -1):
        if filtered is not None and whole is not None:
            return (f"<div class='sum tnum' id='sum'>{scope}"
                    f"<div><i>전체 지출</i><b>{_money(whole[1])}</b></div>"
                    f"<div class='filtered-total'><i>검색 결과 지출</i><b>{_money(filtered[1])}</b></div>"
                    f"<span class='n'>전체 지출 {whole[3]}건 · 검색 결과 지출 {filtered[3]}건</span></div>")
        return (f"<div class='sum tnum' id='sum'>{scope}"
                f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
                f"<span class='n'>지출 {len(expenses)}건</span></div>")
    if filtered is None or whole is None:
        return (
            f"<div class='sum tnum' id='sum'>{scope}<div><i>{ui_icons.icon('book-open')}수입</i><b>{_money(income)}</b></div>"
            f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
            f"<div><i>{ui_icons.icon('arrow-up-down')}차액</i><b>{_money(income - expense)}</b></div>"
            f"<span class='n'>수입 {len(incomes)}건 · 지출 {len(expenses)}건</span></div>" + note)
    fincome, fexpense, finc, fexp = filtered
    wincome, wexpense, winc, wexp = whole
    return (
        f"<div class='sum tnum' id='sum'>{scope}"
        f"<div><i>전체 수입</i><b>{_money(wincome)}</b></div>"
        f"<div><i>전체 지출</i><b>{_money(wexpense)}</b></div>"
        f"<div><i>검색 결과 수입</i><b>{_money(fincome)}</b></div>"
        f"<div><i>검색 결과 지출</i><b>{_money(fexpense)}</b></div>"
        f"<div><i>검색 결과 차액</i>"
        f"<b>{_money(fincome - fexpense)}</b></div>"
        f"<span class='n'>전체 수입 {winc}건 · 전체 지출 {wexp}건"
        f" · 검색 결과 수입 {finc}건 · 검색 결과 지출 {fexp}건</span></div>" + note)


def _trip_options(current="", blank_label=None) -> str:
    options = []
    if blank_label:
        options.append(f"<option value=''>{board.esc(blank_label)}</option>")
    for trip in board.live_trips():
        options.append(
            f"<option value='{board.esc(trip['tab_id'])}'"
            f"{' selected' if trip['tab_id'] == current else ''}>"
            f"{board.esc(trip['display_key'])} · {board.esc(trip['starts_on'])}~"
            f"{board.esc(trip['ends_on'])}</option>")
    return "".join(options)


def _row_kind_meter(row) -> str:
    if row.get("row_kind") == "income":
        return "수입"
    state = row.get("classification_state")
    if state == "unclassified" or row.get("display_tab_id") is None:
        return "대기"
    if row.get("event_kind") == "cancellation":
        return "취소"
    return "지출"


def _income_kind_label(row) -> str:
    return INCOME_KIND_LABELS.get(row.get("income_kind") or "", row.get("income_kind") or "-")


def _row_amount_class(row) -> str:
    amount = board._shown_amount(row)
    if amount < 0:
        return "a-neg"
    return "a-in" if row.get("row_kind") == "income" else "a-ex"


def _row_party_main(row) -> str:
    """Merchant/description first; reservation second as sub. Income keeps fallback."""
    if row.get("row_kind") == "income":
        for key in ("description", "customer_name"):
            value = str(row.get(key) or "").strip()
            if value:
                return value
        return str(row.get("source_merchant") or "").strip() or "-"
    merchant = str(row.get("source_merchant") or "").strip()
    description = str(row.get("description") or "").strip()
    if merchant:
        return merchant
    if description:
        return description
    return str(row.get("reservation_no") or "").strip() or "-"


def _row_party_sub(row) -> str:
    """Display each known reservation once, without modifying the source row."""
    main = _row_party_main(row)
    if row.get("row_kind") == "income":
        for key in ("source_merchant", "nickname"):
            value = str(row.get(key) or "").strip()
            if value and value != main:
                return value
        return ""
    reservation = str(row.get("reservation_no") or "").strip()
    description = str(row.get("description") or "").strip()
    item = str(row.get("item") or "").strip()
    parts = []
    # A lodging or flight row names its stay or its passengers instead of the number;
    # the number itself stays in the row, the search and the source link.
    if item == "\uD56D\uACF5\uB8CC" and reservation:
        parts.append(_passenger_text(row))
    elif reservation and reservation != main:
        parts.append("\uC608\uC57D\uBC88\uD638 " + reservation)
    if reservation:
        description = re.sub(
            r"(?<![\w-])(?:\uC608\uC57D(?:\uBC88\uD638)?\s*)?" + re.escape(reservation)
            + r"(?![\w-])", "", description)
        description = re.sub(r"\s+", " ", description).strip(" \u00b7|,;:-")
    # The typed description is kept verbatim; the bare category name adds nothing.
    if description and description != main and not (item in ("\uC219\uBC15\uBE44", "\uD56D\uACF5\uB8CC") and description == item):
        parts.append(description)
    return " \u00b7 ".join(parts)


_STAY_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
# A sanity bound only: a long stay with a clear period is real. Reversed or invalid dates are unknown.
_MAX_STAY_DAYS = 366


def _stay_text(row) -> str:
    """The lodging dates from the source's service period, never from the reservation number.

    A missing, unreadable, reversed or implausibly long period is shown as unknown
    rather than guessed. The card's approval or payment date is a different fact.
    """
    from datetime import date, timedelta
    unknown = "\uC774\uC6A9\uC77C \uD655\uC778 \uD544\uC694"
    match = _STAY_PATTERN.fullmatch(str(row.get("service_period") or "").strip())
    if not match:
        return unknown
    try:
        start, end = (date.fromisoformat(value) for value in match.groups())
    except ValueError:
        return unknown
    if not start <= end <= start + timedelta(days=_MAX_STAY_DAYS):
        return unknown
    nights = (end - start).days
    stay = f"{nights}박" if nights else "당일"
    return f"{_day_label(start, start.year != end.year)} ~ {_day_label(end, start.year != end.year)} · {stay}"


def _day_label(day, with_year: bool) -> str:
    """A calendar day as read on a ledger line: 10월 14일(수), with the year when the stay crosses one."""
    weekday = "월화수목금토일"[day.weekday()]
    prefix = f"{day.year}년 " if with_year else ""
    return f"{prefix}{day.month}월 {day.day}일({weekday})"


def _flight_passengers() -> dict:
    """The passenger index the OTA refresh holds in memory, read without computing anything."""
    return read_scope.remember("flight_passengers", _load_flight_passengers)


def _load_flight_passengers() -> dict:
    from . import ota_payment_review
    store = board._active_store()
    if store is None or not ota_payment_review.enabled():
        return {}
    return ota_payment_review.passenger_index_for(store)


def _passenger_text(row) -> str:
    """Who is flying, only when the mail names the passengers of this booking."""
    found = _flight_passengers().get(str(row.get("reservation_no") or "").strip())
    if not found or found.get("conflict") or not found.get("names"):
        return "\uD0D1\uC2B9\uC790 \uD655\uC778 \uD544\uC694"
    names = found["names"]
    if len(names) == 1:
        return f"\uD0D1\uC2B9\uC790: {names[0]}"
    return f"\uD0D1\uC2B9\uC790: {names[0]} \uC678 {len(names) - 1}\uBA85"


def _row_item(row) -> str:
    """분류: the typed 항목, or the income kind, or "-" when the row has neither.

    Filled from what the row holds, not from the section it sits in: a waiting
    expense has no 여행 and still has a 항목.
    """
    value = str(row.get("item") or "").strip()
    if value:
        return value
    if row.get("row_kind") == "income":
        return _income_kind_label(row)
    return "-"


def _party_cell(row) -> str:
    """거래처·내용: the counterparty and what the transaction was, in one cell.

    One cell rather than two columns, because reading a ledger is a single left
    to right pass: the amount has to sit against the line that explains it.
    """
    main = f"<span class='s-main'>{board.esc(_row_party_main(row))}</span>"
    sub = _row_party_sub(row)
    if sub:
        main += f"<span class='s-sub'>{board.esc(sub)}</span>"
    return (f"<td class='c-party'><span class='party-line'>{_merchant_icon(row)}"
            f"<span class='party-copy'>{main}</span></span></td>")


def _move_form(row, move_back: str) -> str:
    """The travel picker a waiting row carries, in its own action row now."""
    rid = row["row_id"]
    return (
        "<form method='post' action='/api/rows/"
        f"{board.esc(rid)}/save' data-js-move class='row-move'>"
        f"<input type='hidden' name='csrf' value='{board.CSRF_TOKEN}'>"
        f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
        "<input type='hidden' name='client_request_id' value='"
        f"{uuid.uuid4().hex}'>"
        "<input type='hidden' name='change_mode' value='exception'>"
        f"<input type='hidden' name='return_to' value='{board.esc(move_back)}'>"
        "<label class='sr' for='move-" + board.esc(rid) + "'>이동할 여행</label>"
        f"<select class='psel' id='move-{board.esc(rid)}' name='display_tab_id'>"
        f"{_trip_options('', '분류대기(여행 미정)')}</select>"
        f"<button class='btn' type='submit'>{ui_icons.icon('check')}이동</button></form>")


def _table_html(rows, *, kind, selected, unclassified, move_back="/board") -> str:
    if not rows:
        return ("<tbody><tr class='empty'><td colspan='5'>"
                f"{'수입 내역이 없어요' if kind == 'income' else '지출 내역이 없어요'}"
                "</td></tr></tbody>")
    body = []
    for row in rows:
        rid = row["row_id"]
        amount = board._shown_amount(row)
        item = row.get('item') or ''
        # A keyboard reader reaches a row the way a pointer reader does, so the row
        # itself is focusable and Enter or Space opens it. `tabindex` is what
        # makes that possible; the click path is unchanged underneath.
        # Five columns: the memo column is gone from the table. The operator note
        # stays in storage, search and the edit panel; only its table cell is gone.
        body.append(
            f"<tr data-id='{board.esc(rid)}' tabindex='0'"
            f"{' aria-selected="true"' if rid == selected else ''}>"
            f"<td class='c-date tnum'>{board.esc(board._shown_date(row))}</td>"
            f"{_party_cell(row)}"
            f"<td class='c-item'><span class='category-line'>{_category_icon(row)}{board.esc(_row_item(row))}</span></td>"
            f"<td class='c-stay'>{board.esc(_stay_text(row)) if item == '숙박비' else ''}</td>"
            + f"<td class='num tnum c-amt {_row_amount_class(row)}'>{_money(amount)}</td>"
            f"</tr>")
        if unclassified:
            # The waiting row's travel picker lives in its own action row below
            # the data row, not in the removed memo cell. Same form contract.
            body.append(
                f"<tr class='move-row' data-move-for='{board.esc(rid)}'>"
                f"<td colspan='5'>{_move_form(row, move_back)}</td></tr>")
    return f"<tbody>{''.join(body)}</tbody>"


def _column_head_row() -> str:
    """Column titles repeated above the expense rows (display only)."""
    return ("<tr><th scope='col'>날짜</th><th scope='col'>거래처·내용</th>"
            "<th scope='col'>분류</th><th scope='col'>이용일</th>"
            "<th scope='col' class='num'>금액</th></tr>")


def _tables_html(incomes, expenses, *, selected, unclassified, move_back="/board") -> str:
    head = (
        "<div class='tw'><table id='tbl'>"
        "<caption class='sr'>거래 내역. 수입은 위, 지출은 아래에 있습니다.</caption>"
        # Five columns, and the widths are given to the fixed ones so the counterparty
        # and content column takes whatever is left. The amount is the last column
        # and stays right-aligned, because a ledger is read by comparing the
        # amount column down, not across.
        "<colgroup><col style='width:108px'><col><col style='width:104px'>"
        "<col style='width:150px'>"
        "<col style='width:126px'></colgroup>"
        "<thead><tr><th scope='col'>날짜</th><th scope='col'>거래처·내용</th>"
        "<th scope='col'>분류</th><th scope='col'>이용일</th>"
        "<th scope='col' class='num'>금액</th></tr></thead>")
    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    income_group = (
        f"<tbody class='grp'><tr><th scope='colgroup' colspan='4'>수입 (COST 기록) "
        f"<a href='#google-trip-income'>수입내역 보기</a></th>"
        f"<th class='num'>{_money(income_total)}</th></tr></tbody>"
        + _table_html(incomes, kind="income", selected=selected, unclassified=False)
    ) if incomes else ''
    groups = (
        income_group + "<tbody class='grp'><tr><th scope='colgroup'>지출</th>"
        "<td colspan='3'><a class='btn' id='add-manual-expense' href='/expense/new'>"
        f"{ui_icons.icon('pencil')}수기 지출 추가</a></td>"
        f"<th class='num'>{_money(expense_total)}</th></tr></tbody>"
        + "<tbody class='colhead'>" + _column_head_row() + "</tbody>"
        + _table_html(expenses, kind="expense", selected=selected,
                      unclassified=unclassified, move_back=move_back)
        + "</table></div>")
    return head + groups


def _mobile_html(incomes, expenses, *, selected, unclassified,
                  move_back="/board") -> str:
    def item(row):
        rid = row["row_id"]
        move = ""
        if unclassified:
            move = (
                "<form method='post' action='/api/rows/"
                f"{board.esc(rid)}/save' data-js-move>"
                f"<input type='hidden' name='csrf' value='{board.CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                "<input type='hidden' name='client_request_id' value='"
                f"{uuid.uuid4().hex}'>"
                "<input type='hidden' name='change_mode' value='exception'>"
                f"<input type='hidden' name='return_to' value='{board.esc(move_back)}'>"
                f"<label class='sr' for='mobile-move-{board.esc(rid)}'>이동할 여행</label>"
                f"<select class='psel' id='mobile-move-{board.esc(rid)}' name='display_tab_id'>"
                f"{_trip_options('', '분류대기(여행 미정)')}</select>"
                f"<button class='btn' type='submit'>{ui_icons.icon('check')}이동</button></form>")
        cls = "li pend" if unclassified else "li"
        # Two-line business summary only: date, kind tag, category, vendor,
        # purpose, amount. The origin detail lives in the edit panel, so no
        # per-row details element here (density first).
        kind = _row_kind_meter(row)
        cat = row.get("item") or _income_kind_label(row) or "-"
        main_text = _row_party_main(row)
        sub_text = _row_party_sub(row)
        headline = " \u00b7 ".join(text for text in (main_text, sub_text) if text)
        tag_cls = "tag in" if kind == "수입" else "tag"
        return (
            f"<button class='{cls}' type='button' data-id='{board.esc(rid)}'"
            f"{' aria-selected="true"' if rid == selected else ''}>"
            f"<span class='m-row'><span class='d tnum'>"
            f"{board.esc(board._shown_date(row))}</span>"
            f"<span class='{tag_cls}'>{board.esc(kind)}</span>"
            f"<span class='m-cat category-line'>{_category_icon(row)}{board.esc(cat)}</span>"
            f"<span class='a tnum {_row_amount_class(row)}'>"
            f"{_money(board._shown_amount(row))}</span></span>"
            f"<span class='party-line mobile-party'>{_merchant_icon(row)}<span class='t'>{board.esc(headline)}</span></span></button>{move}")

    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    income_group = (
        f"<p class='lg'><span>기존 수입</span><span class='tnum'>{_money(income_total)}</span></p>"
        + ''.join(item(r) for r in incomes)
    ) if incomes else ''
    return (
        "<div class='lst'>"
        + income_group +
        f"<p class='lg'><span>지출</span><span class='tnum'>{_money(expense_total)}</span>"
        "<a class='btn' id='add-manual-expense-mobile' href='/expense/new'>"
        f"{ui_icons.icon('pencil')}수기 지출 추가</a></p>"
        f"{''.join(item(r) for r in expenses) or '<p class=\"muted\" style=\"padding:12px 16px\">지출 내역이 없어요</p>'}"
        "</div>")


# --------------------------------------------------------------- edit panel
def _panel_html(row, kind, *, csrf, rule_case, error, message, back, draft) -> str:
    allowed, fixed = board.editable_fields(kind, row.get("source_kind", ""),
                                           bool(row.get("is_allocation")))
    rev = row.get("revision", 1)
    amount = board._shown_amount(row)
    fields = []

    def text_field(name, label, value, *, ro=False, placeholder=""):
        # A locked source field carries no name, so neither a scripted nor a
        # plain form post can send it. The endpoint keeps its own refusal.
        return (f"<div class='f'><label for='f-{name}'>{label}</label>"
                f"<input id='f-{name}'{'' if ro else f" name='{name}'"}"
                f" class='tnum' type='text'"
                f" value='{board.esc(value or '')}'"
                f"{' readonly' if ro else ''} placeholder='{board.esc(placeholder)}'>"
                "</div>")

    def value_of(name, stored):
        if name in draft and draft[name] is not None:
            return draft[name]
        return stored

    # A field the endpoint fixes is a record, not a decision, so it is folded away
    # with the source identifiers. A field the endpoint allows stays in the open
    # form: an income row's date and amount are editable, and a locked input the
    # reader cannot reach is not an edit form.
    locked = []
    editable_source = []
    date_field = text_field("occurred_on",
                            "거래 날짜" if "occurred_on" not in fixed else "거래 날짜 (고정)",
                            board._shown_date(row), ro="occurred_on" in fixed)
    amount_field = text_field(
        "amount_krw", "거래 금액" if "amount_krw" not in fixed else "거래 금액 (고정)",
        f"{amount:,}", ro="amount_krw" in fixed)
    (locked if "occurred_on" in fixed else editable_source).append(date_field)
    (locked if "amount_krw" in fixed else editable_source).append(amount_field)
    locked.append(text_field("reservation_no", "예약번호 (고정)",
                             row.get("reservation_no", ""), ro=True))
    if len(editable_source) == 2:
        fields.append("<div class='grid2'>" + "".join(editable_source) + "</div>")
    else:
        fields.extend(editable_source)

    current_tab = value_of("display_tab_id", row.get("display_tab_id") or "")
    fields.append(
        "<div class='f'><label for='f-display_tab_id'>여행</label>"
        f"<select id='f-display_tab_id' name='display_tab_id'{' disabled' if 'display_tab_id' not in allowed else ''}>"
        f"{_trip_options(current_tab, '분류대기(여행 미정)')}</select></div>")
    for name, label in (("item", "항목"), ("customer_name", "이름"),
                        ("nickname", "닉네임"), ("customer_id", "고객 ID"),
                        ("income_kind", "입금 종류")):
        if name not in allowed and name not in fixed:
            continue
        if name == "income_kind":
            stored = row.get("income_kind") or ""
        else:
            stored = row.get(name, "")
        fields.append(text_field(name, label, value_of(name, stored),
                                 ro=name in fixed))
    if "description" in allowed or "description" in fixed:
        fields.append(text_field("description", "용도",
                                 value_of("description", row.get("description", "")),
                                 ro="description" in fixed))
    fields.append(
        "<div class='f'><label for='f-operator_note'>메모</label>"
        f"<textarea id='f-operator_note' name='operator_note'"
        f"{' disabled' if 'operator_note' not in allowed else ''}>"
        f"{board.esc(value_of('operator_note', row.get('operator_note')) or '')}"
        "</textarea></div>")
    fields.append(
        "<div class='f'><label for='f-change_mode'>변경 이유</label>"
        "<select id='f-change_mode' name='change_mode'>"
        "<option value='exception'>예외 처리 (이 건만)</option>"
        "<option value='rule_change'>규칙 변경 (반복되는 경우)</option>"
        "</select></div>")
    if error:
        text = board.esc(error) + (f" — {board.esc(message)}" if message else "")
        note = f"<p class='f-msg err' role='alert'>{text}</p>"
    elif message:
        note = f"<p class='f-msg' role='status'>{board.esc(message)}</p>"
    else:
        # The line always exists, so a save result has somewhere to go without
        # rebuilding the panel.
        note = "<p class='f-msg' role='status'></p>"
    rule_link = ""
    if rule_case:
        rule_link = (f"<a id='rule-open' href='/rules?case={board.esc(rule_case)}'>"
                     "규칙 대화 열기</a>")
    links = [f"<a href='/row?id={board.esc(row['row_id'])}'>상세·이력</a>"]
    if row.get("row_kind") == "income":
        links.append(f"<a href='/income/{board.esc(row['row_id'])}/split'>배분</a>")
    links.append(f"<a href='/trips'>여행 관리</a>")
    links.append(f"<a href='/export'>선택 탭 출력</a>")
    links.append(rule_link)
    from . import ui_icons as _panel_icons
    return (
        # `data-row` is which row this panel belongs to. The browser reads it to
        # move to the previous or next row that is actually on screen and to keep
        # exactly one row marked as selected, so the two cannot drift apart.
        "<aside class='panel' id='panel' tabindex='-1'"
        f" data-row='{board.esc(row['row_id'])}' aria-label='거래 상세 편집 패널'>"
        "<div class='p-hd'><div>"
        f"<h2>거래 상세</h2><p class='p-amt tnum'>{_money(amount)}</p></div>"
        "<button class='icon' id='p-close' type='button' aria-label='패널 닫기'>×</button>"
        "</div>"
        "<form method='post' action='/api/rows/"
        f"{board.esc(row['row_id'])}/save' data-js-save>"
        f"<input type='hidden' name='csrf' value='{board.esc(csrf)}'>"
        f"<input type='hidden' name='expected_revision' value='{rev}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<input type='hidden' name='return_to' value='{board.esc(back)}'>"
        "<div class='p-bd'>"
        # The source identifier, the revision, the source kind and every field the
        # endpoint fixes are what a support answer needs and what a working day
        # does not, so they are folded away here and opened on demand. Nothing is
        # removed and no input loses its selector or its missing name: a locked
        # field is still the same input with no `name`, so no post can send it.
        f"{''.join(fields)}{note}"
        "<details class='p-src'>"
        "<summary>원본 정보</summary>"
        f"<p class='p-sub'>{board.esc(row.get('source_event_id') or row['row_id'])}"
        f" · revision {rev} · {board.esc(row.get('source_kind') or '')}"
        f" · 가맹점 {board.esc(row.get('source_merchant') or '-')}</p>"
        f"{''.join(locked)}"
        "</details>"
        "<p class='src'>원천 날짜·금액·예약번호는 읽기 전용이에요. 여행·항목·용도·메모는 "
        "수정할 수 있습니다.</p>"
        f"<div class='p-links'>{' · '.join(x for x in links if x)}</div>"
        "</div>"
        "<div class='p-ft'>"
        # The two walking buttons start hidden and are shown by the script from
        # the rows that are on screen. A button that cannot go anywhere is not
        # drawn, so nothing here promises a move the ledger cannot make.
        "<button class='btn p-nav' type='button' id='p-prev' hidden"
        f" aria-label='이전 거래'>{_panel_icons.icon('chevron-left')}이전</button>"
        "<button class='btn p-nav' type='button' id='p-next' hidden"
        f" aria-label='다음 거래'>다음{_panel_icons.icon('chevron-right')}</button>"
        "<span class='p-count tnum' id='p-count'></span>"
        f"<button class='btn primary' type='submit'>{_panel_icons.icon('save')}저장 "
        "<kbd class='kbd'>Ctrl</kbd>+<kbd class='kbd'>Enter</kbd></button>"
        f"<a class='btn' id='p-cancel' href='{board.esc(back)}'>취소 "
        "<kbd class='kbd'>Esc</kbd></a>"
        "</div></form></aside>")


# -------------------------------------------------------------------- pages
def state_query(tab_id: str, query: str = "", kind: str = "", archived: str = "") -> str:
    """Every in-app link carries the view state, so a trip switch or a refresh
    keeps the search, the filter and the archived drawer as they were."""
    parts = [f"tab={tab_id}"]
    if query:
        parts.append(f"q={quote(query)}")
    if kind:
        parts.append(f"kind={kind}")
    if archived:
        parts.append(f"arch={quote(archived)}")
    return "&".join(parts)


def _last_saved_at(tab_id: str) -> str:
    """When this tab's rows were last saved, for the global header.

    APP_SPEC 4.1 puts `저장되지 않은 변경 1건`과 마지막 저장 시각 in the global
    top area. The time is read from the append-only change ledger, so it is the
    real last save rather than a value the page made up.
    """
    if _STORE_missing():
        return ""
    try:
        if tab_id:
            row = board._STORE.conn.execute(
                "SELECT MAX(r.created_at) FROM board_revisions r"
                " JOIN board_rows b ON b.row_id = r.row_id"
                " WHERE b.display_tab_id=? AND r.kind<>'conflict'",
                (tab_id,)).fetchone()
        else:
            row = board._STORE.conn.execute(
                "SELECT MAX(created_at) FROM board_revisions"
                " WHERE kind<>'conflict'").fetchone()
    except Exception:
        return ""
    if not row or not row[0]:
        return "기록 없음"
    from .google_ledger_page import format_display_time
    return format_display_time(row[0])


def shell(title: str, *, tab_id: str, heading: str, period: str = "",
          meta: str = "", body: str, query: str = "", kind: str = "",
          archived: str = "", aside: str = "", home: bool = False) -> str:
    """The shared chrome for every screen, with the view state in the links."""
    state = state_query(tab_id, query, kind, archived)
    back = f"/board?{state}"
    # APP_SPEC 4.1: the global top area carries the unsaved row count and the
    # last saved time. The count is filled in by the script as edits become
    # dirty; the time is the ledger's own last save for this tab.
    role_note = ("읽기 전용" if board.current_role() == "viewer" else "")
    main_class = "main home-main" if home else "main"
    from . import ui_icons as _icons
    global_state = "" if home else (
        f"<p class='meta' id='global-state' data-role='{board.esc(role_note)}'>"
        "<span id='unsaved-count'>저장되지 않은 변경 없음</span>"
        f"<span>{ui_icons.icon('save')}최근 저장 {_last_saved_at(tab_id)}</span>"
        + (f" · {board.esc(role_note)}" if role_note else "")
        + "</p>")
    # 홈에서는 내보내기 바로가기를 두지 않는다. XLSX 출력은 장부 화면의
    # 내보내기 버튼을 사용한다. /export 기능·권한은 그대로 둔다.
    export_btn = ("" if home
                  else f"<a class='btn primary' href='/export'>{_icons.icon('save')}XLSX 출력</a>")
    main = (
        f"<main class='{main_class}' id='main' tabindex='-1' data-base='{board.esc(back)}'>"
        "<div class='page-hd'><div>"
        f"<h1>{heading}<span class='synth'>{board.data_status_mark()}</span></h1>"
        + (f"<p class='period'>{period}</p>" if period else "")
        + (f"<p class='meta'>{meta}</p>" if meta else "")
        + global_state
        # The cross-screen refresh reports here. The element always exists, so a
        # deferred change, a lost connection and a revoked permission all have
        # somewhere to say so on any screen that carries the shell.
        + "<p class='meta' id='live-status-wrap' aria-live='polite'>"
        "<span class='meta live-ok' id='live-status' hidden></span></p>"
        "</div><div class='act'>"
        f"<a class='btn' href='/import'>{_icons.icon('upload')}카드 가져오기</a>"
        f"{export_btn}"
        f"<a class='btn' href='{board.esc(back)}'>장부</a>"
        "</div></div>"
        f"<div class='page-body'>{body}</div>"
        "</main>")
    slot = f"<div id='panel-slot'>{aside}</div>" if aside else "<div id='panel-slot'></div>"
    return f"<div class='app'>{_nav_html(tab_id, query, kind, archived)}{main}{slot}</div>"


def _selected_trip(tab_id: str):
    if tab_id == "unclassified":
        return {"display_key": "분류대기", "is_unclassified": True}
    return next((t for t in board.live_trips(include_archived=True)
                 if t["tab_id"] == tab_id), None)


def _expense_category_rank(item: str) -> int:
    """Display-only order: 항공 → 숙박 → 교통 → 식비 → 현지경비, rest last.

    Matches existing item names (항공권/항공비/항공료/항공, 숙박비, 교통비,
    식비, 현지경비/현지). 여비교통비는 기존 분류 의미대로 교통에 둔다.
    Store order, accounting, amounts and TSV order are untouched: this only
    orders the ledger screen lists.
    """
    text = str(item or "")
    if "항공" in text:
        return 0
    if "숙박" in text:
        return 1
    if "교통" in text:
        return 2
    if "식비" in text:
        return 3
    if "현지경비" in text or "현지" in text:
        return 4
    return 5


def _sort_expenses_for_display(rows: list) -> list:
    """화면 날짜 오름차순. 같은 날짜에는 기존 분류 순서를 유지한다."""
    return sorted(rows, key=lambda r: (not bool(r.get('occurred_on')), r.get('occurred_on') or '',
                                      _expense_category_rank(r.get("item"))))


def _quarter_body(tab_id: str, message: str = "", error: str = "") -> str:
    """A quarter's cost tab: rows waiting for confirmation, the booked rows, and the one action that books the waiting rows."""
    from app import quarter_tab
    store = board._active_store()
    pending = quarter_tab.pending_rows(store.conn, tab_id) if store is not None else []
    booked = [r for r in board._expense_rows() if r.get('display_tab_id') == tab_id]
    pending_total = sum(int(r['amount_krw'] or 0) for r in pending)
    booked_total = sum(int(r.get('amount_krw') or 0) for r in booked)
    note = (f"<p class='status err' role='alert'>{board.esc(error)}</p>" if error else
            f"<p class='status' role='status'>{board.esc(message)}</p>" if message else "")

    def line(day, merchant, amount):
        return (f"<tr><td>{board.esc(day or '')}</td><td>{board.esc(merchant or '')}</td>"
                f"<td class='num'>{int(amount or 0):,}원</td></tr>")
    waiting = "".join(line((r.get('approval_date') or r.get('posting_date') or '')[:10], r.get('merchant'),
                           r.get('amount_krw')) for r in pending) or "<tr><td colspan='3'>기록 전 거래가 없습니다.</td></tr>"
    done = "".join(line(str(r.get('occurred_on') or '')[:10], r.get('merchant'), r.get('amount_krw'))
                   for r in booked) or "<tr><td colspan='3'>기록된 거래가 없습니다.</td></tr>"
    return ("<div class='body'>" + note +
            "<p class='hint'>새로 수집된 정상 거래는 자동으로 기록됩니다. 잘못 옮겨진 거래만 여행이나 항목을 바꾸세요.</p>"
            f"<h3>기록된 거래 {len(booked)}건 · {booked_total:,}원</h3><table><thead><tr><th>날짜</th><th>상호</th><th>금액</th></tr></thead>"
            f"<tbody>{done}</tbody></table>"
            f"<h3>기록 전 기존 거래 {len(pending)}건 · {pending_total:,}원</h3>"
            "<p class='hint'>자동 기록 시작 이전에 분류된 거래입니다. 확정 단계는 없고, 새로 수집되는 거래는 분류되는 즉시 기록됩니다.</p>"
            f"<table><thead><tr><th>날짜</th><th>상호</th><th>금액</th></tr></thead><tbody>{waiting}</tbody></table></div>")


def _selected_rows(tab_id: str, query: str = "", kind: str = ""):
    """The rows this tab and filter show, and the unfiltered totals beside them.

    DETAILED 12.2: the whole totals are kept beside the filtered ones, so a filter
    never quietly replaces the whole total with the result total. The live refresh
    calls this too, so a refreshed row list and a freshly loaded one are the same
    rows for the same tab and filter. Expenses are display-sorted by category;
    totals and store order are unchanged.
    """
    if tab_id == "unclassified":
        incomes = [r for r in board._income_rows() if r.get("display_tab_id") is None]
        expenses = board._unclassified_rows()
    else:
        incomes = [r for r in board._income_rows() if r.get("display_tab_id") == tab_id]
        expenses = [r for r in board._expense_rows() if r.get("display_tab_id") == tab_id]
    if kind == "in":
        expenses = []
    elif kind == "ex":
        incomes = []
    whole_income, whole_expense = list(incomes), list(expenses)
    if board.current_role() == 'owner':
        from .refund_tab import member_ids
        paired = member_ids(board._active_store())
        expenses = [r for r in expenses if r.get('source_event_id') not in paired]
        whole_expense = [r for r in whole_expense if r.get('source_event_id') not in paired]
    if query:
        def keep(row):
            blob = " ".join(str(row.get(key) or "") for key in (
                "item", "description", "operator_note", "reservation_no",
                "source_merchant", "customer_name"))
            return query in blob
        incomes = [r for r in incomes if keep(r)]
        expenses = [r for r in expenses if keep(r)]
    expenses = _sort_expenses_for_display(expenses)
    incomes = sorted(incomes, key=lambda r: (not bool(r.get('occurred_on')), r.get('occurred_on') or ''))
    return incomes, expenses, whole_income, whole_expense


@read_scope.scoped
def page(tab_id: str, query: str = "", kind: str = "", selected: str = "",
         error: str = "", message: str = "", archived: str = "",
         draft: dict = None, back: str = "") -> str:
    """The main ledger screen in the new design."""
    if _STORE_missing():
        return board.layout("웹 장부", "<div class='body'><p>저장소가 연결되지 않았어요.</p></div>")
    from app import quarter_tab
    if quarter_tab.parse_tab(tab_id):
        year, quarter = quarter_tab.parse_tab(tab_id)
        title = f"{year}년 {quarter}분기 기타비용"
        return shell(title, tab_id=tab_id, heading=title, query=query,
                     body=_quarter_body(tab_id, message, error))
    if tab_id == 'refunds':
        from .refund_tab import render as refund_body
        return shell('환불', tab_id='refunds', heading='환불', query=query,
                     body=_bar_html(query, kind, 'refunds', archived) +
                     "<div id='live-sum'></div><div id='live-rows'>" +
                     refund_body(board._active_store(), query, kind) + '</div>')
    trip = _selected_trip(tab_id)
    from .google_ledger_page import trip_income_html
    incomes, expenses, whole_income, whole_expense = _selected_rows(tab_id, query, kind)
    unclassified = tab_id == "unclassified"
    status = ""
    if error:
        status = f"<p class='status err' id='status' role='alert'>{board.esc(error)}</p>"
    elif message:
        status = (f"<p class='status' id='status' role='status'>"
                  f"{board.esc(message)}</p>")
    else:
        status = ("<p class='status hint' id='status' role='status' aria-live='polite'></p>")
    back = back or ("/board?" + state_query(tab_id, query, kind, archived))
    panel = ""
    if selected:
        panel = panel_part(selected, back=back, error=error, message=message,
                           draft=draft or {})
    main = (
        f"<main class='main' id='main' tabindex='-1' data-base='{board.esc(back)}'><div class='main-wrap'>"
        f"{_head_html(trip)}"
        f"{_bar_html(query, kind, tab_id, archived)}{status}"
        # APP_SPEC 4.1: the same global state line the shared shell carries.
        f"<p class='meta' id='global-state' data-role='"
        f"{board.esc('읽기 전용' if board.current_role() == 'viewer' else '')}'>"
        "<span id='unsaved-count'>저장되지 않은 변경 없음</span>"
        f"<span>{ui_icons.icon('save')}최근 저장 {_last_saved_at(tab_id)}</span></p>"
        # APP_SPEC 4.1: ledger-note removed per review
        # The live refresh replaces the totals and the two row lists as one block,
        # and the edit panel sits outside it so an open panel is never rewritten.
        f"<div id='live-sum'>"
        f"{summary_part(tab_id, kind, query)}"
        f"</div>"
        f"<section id='trip-income' aria-label='여행 수입 · COST 기록'>"
        f"{trip_income_html(tab_id)}"
        f"</section>"
        f"{_source_preview_html(trip)}"
        f"{rows_region(tab_id, query, kind, selected, archived, back)}"
        "<p class='meta' id='live-status-wrap' aria-live='polite'>"
        "<span class='meta live-ok' id='live-status' hidden></span></p>"
        "</div></main>")
    return (f"<div class='app'>"
            f"{_nav_html(tab_id, query, kind, archived)}{main}"
            f"<div id='panel-slot'>{panel}</div></div>")


def panel_part(row_id: str, *, back: str = "/board", error: str = "",
               message: str = "", draft: dict = None) -> str:
    """Just the edit panel, for a row click without a full page load."""
    if _STORE_missing() or not row_id:
        return ""
    kind, row = board.find_row(row_id)
    if row is None:
        return ("<aside class='panel'><div class='p-bd'>"
                "<p class='muted'>없는 거래예요</p></div></aside>")
    return _panel_html(row, kind, csrf=board.CSRF_TOKEN,
                       rule_case=board.learning_case_id(row_id),
                       error=error, message=message, back=back, draft=draft or {})


def summary_part(tab_id: str, kind: str = "", query: str = "") -> str:
    if tab_id == 'refunds':
        return ''
    if _STORE_missing():
        return ""
    _, _, whole_income, whole_expense = _selected_rows(tab_id, '', kind)
    recorded_income_count = len(whole_income)
    if kind == "in":
        whole_expense = []
    elif kind == "ex":
        whole_income = []

    def totals(rows_in, rows_ex):
        return (sum(board._shown_amount(r) for r in rows_in),
                sum(board._shown_amount(r) for r in rows_ex),
                len(rows_in), len(rows_ex))

    if not query:
        return _summary_html(whole_income, whole_expense, recorded_income_count=recorded_income_count)
    # DETAILED 12.2: a filter separates the names; the whole total stays whole.
    needle = query.strip()
    shown_in = [r for r in whole_income if _matches(r, needle)]
    shown_ex = [r for r in whole_expense if _matches(r, needle)]
    return _summary_html(
        shown_in, shown_ex,
        recorded_income_count=recorded_income_count,
        filtered=totals(shown_in, shown_ex),
        whole=totals(whole_income, whole_expense))


def rows_region(tab_id: str, query: str = "", kind: str = "", selected: str = "",
                archived: str = "", back: str = "") -> str:
    """The two row lists inside the one element a live refresh replaces.

    One renderer, embedded by the full page and re-rendered for a fragment, so the
    two cannot disagree about which rows exist, which one is selected, or which
    move form a row carries.
    """
    if _STORE_missing():
        return ""
    incomes, expenses, _whole_income, _whole_expense = _selected_rows(
        tab_id, query, kind)
    unclassified = tab_id == "unclassified"
    back = back or ("/board?" + state_query(tab_id, query, kind, archived))
    return (f"<div id='live-rows'>"
            f"{_tables_html(incomes, expenses, selected=selected, unclassified=unclassified, move_back=back)}"
            f"{_mobile_html(incomes, expenses, selected=selected, unclassified=unclassified, move_back=back)}"
            f"</div>")


def rows_part(tab_id: str, query: str = "", kind: str = "", selected: str = "",
              archived: str = "") -> str:
    """The row lists' contents for a live fragment, without the region's element.

    The live sync adds that wrapper, so a bundle written here and a page rendered
    here cannot both carry `id='live-rows'` and end up with the id twice on screen.

    No "is this a real trip" test here. `분류대기` is not a trip in `trip_tabs`, so
    a guard that asked `_selected_trip` would return an empty fragment for the
    unassigned bucket, and the rows waiting there would never appear however often
    something was added to it or moved into it.
    """
    if _STORE_missing():
        return ""
    if tab_id == 'refunds':
        from .refund_tab import render as refund_body
        return refund_body(board._active_store(), query, kind)
    incomes, expenses, _whole_income, _whole_expense = _selected_rows(
        tab_id, query, kind)
    unclassified = tab_id == "unclassified"
    back = "/board?" + state_query(tab_id, query, kind, archived)
    return (f"{_tables_html(incomes, expenses, selected=selected, unclassified=unclassified, move_back=back)}"
            f"{_mobile_html(incomes, expenses, selected=selected, unclassified=unclassified, move_back=back)}")


def viewer_trips_html(trips) -> str:
    """A viewer's own trips with their totals, for the viewer board and its
    live refresh alike.

    The caller passes trips that have already been filtered by the access store.
    This function only renders them, so there is no path here that could name a
    trip the viewer was not given.
    """
    if not trips:
        return ("<div class='sect'><h2>담당 여행</h2>"
                "<p>현재 배정된 여행이 없습니다</p></div>")
    items = "".join(
        f"<li><a href='/board?tab={board.esc(t['tab_id'])}'>{board.esc(t['display_key'])}</a>"
        f" — {board.esc(t['starts_on'])}~{board.esc(t['ends_on'])}"
        f" · 수입 {t['income_krw']:,}원 · 지출 {t['expense_krw']:,}원"
        f" · 차액 {t['balance_krw']:,}원</li>"
        for t in trips)
    return f"<div class='sect'><h2>담당 여행</h2><ul>{items}</ul></div>"


def _matches(row: dict, needle: str) -> bool:
    """Does this row contain the search text, over the fields the screen shows."""
    if not needle:
        return True
    hay = " ".join(str(row.get(f) or "") for f in (
        "occurred_on", "item", "description", "customer_name", "nickname",
        "reservation_no", "service_period", "source_merchant", "operator_note",
        "display_tab_id", "income_kind", "evidence_type"))
    return needle in hay


def _totals_kw(query, shown_in, shown_ex, whole_in, whole_ex) -> dict:
    """The summary's keyword arguments, split only when a filter is on."""
    if not query:
        return {}

    def totals(rows_in, rows_ex):
        return (sum(board._shown_amount(r) for r in rows_in),
                sum(board._shown_amount(r) for r in rows_ex),
                len(rows_in), len(rows_ex))

    return {"filtered": totals(shown_in, shown_ex),
            "whole": totals(whole_in, whole_ex)}


def _STORE_missing() -> bool:
    return getattr(board, "_STORE", None) is None


def render(page_html: str, title: str = "웹 장부", live_config: str = "") -> str:
    """Wrap a design fragment in the document with the design stylesheet.

    `live_config` is the JSON the cross-screen refresh script reads. It is
    optional so a screen that has nothing to poll (a login page, a rule dialog)
    simply carries no script rather than an empty one that asks for nothing.
    """
    from . import live_sync

    live = (f"{live_config}<script>{live_sync.SCRIPT}</script>"
            if live_config else "")
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{board.esc(title)}</title><style>{STYLE}</style></head>"
        f"<body>{page_html}<script>{SCRIPT}</script>{live}</body></html>")
