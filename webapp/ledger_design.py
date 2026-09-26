"""A/Ramp/Pretendard design applied to the real ledger screens.

The screen is server rendered and talks to the existing store, save, upload,
export and rule dialog contracts. Nothing in this module re-implements them,
and no demo data or demo JavaScript is copied in: the demo only supplied the
layout, the colours and the font.

`static_asset` is the only way a file leaves this package, and it answers from
an explicit allowlist, so a path can never escape it.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import quote

from . import ledger_board as board

FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"

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
 --bg:#F7F8F7;--paper:#FFFFFF;--ink:#202521;--mut:#657068;--line:#E3E7E3;
 --line2:#EEF1EE;--sel:#E9F3ED;--grn:#1C7A52;--grn-dk:#166444;--grn-lt:#F1F7F3;
 --warn:#8A5A12;--neg:#A4342A;
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
:focus-visible{outline:2px solid var(--grn);outline-offset:1px}
.synth{display:inline-block;font-size:11.5px;line-height:17px;padding:0 7px;border:1px solid var(--line);
 border-radius:3px;color:var(--mut);margin-left:8px;vertical-align:2px}

.app{display:flex;height:100dvh;min-height:0}
.nav{width:232px;flex:0 0 232px;background:var(--bg);border-right:1px solid var(--line);
 display:flex;flex-direction:column;min-height:0;overflow:auto}
.nav-hd{padding:16px 16px 12px}
.brand{font-size:15px;font-weight:700}
.brand small{display:block;font-size:11.5px;font-weight:400;color:var(--mut);margin-top:3px}
.nav-sec{padding:12px 16px 6px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.05em}
.nav-q{margin:0 12px 6px}
.nav-q input{width:100%;height:32px;border:1px solid var(--line);border-radius:4px;
 background:var(--paper);padding:0 8px;font-size:13px}
.nav-list{list-style:none;margin:0;padding:0 8px}
.nv{display:flex;align-items:center;gap:8px;width:100%;min-height:36px;padding:6px 8px;
 border:0;border-left:2px solid transparent;border-radius:0;background:transparent;
 font-size:14px;font-weight:400;text-align:left;cursor:pointer;color:var(--ink);text-decoration:none}
.nv:hover{background:var(--line2)}
.nv[aria-pressed="true"],.nv.sel{background:var(--sel);border-left-color:var(--grn);font-weight:600}
.nv .nm{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nv .ct{flex:0 0 auto;margin-left:8px;font-size:12px;color:var(--mut);white-space:nowrap}
.nv .ct.warn{color:var(--warn)}
.nav-arch .nm{color:var(--mut)}
.nav-toggle{border-left:2px solid transparent;margin:0 8px;max-width:calc(100% - 16px)}
.nav-toggle .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav-toggle .ct{flex:0 0 auto}
.nav-toggle[aria-expanded="true"]{background:var(--line2)}
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
.nav-mask{display:none}

.main{flex:1 1 auto;min-width:0;overflow:auto;background:var(--paper)}
.page-hd{display:flex;align-items:flex-start;gap:16px;padding:20px 24px 14px;
 border-bottom:1px solid var(--line)}
.page-hd h1{font-size:20px;font-weight:700;letter-spacing:-.012em;line-height:1.25}
.period{font-size:13px;color:var(--mut);margin-top:3px}
.meta{font-size:12.5px;color:var(--mut);margin-top:6px;display:flex;flex-wrap:wrap;gap:4px 14px}
.meta a{color:var(--mut)}
.act{margin-left:auto;display:flex;gap:8px;flex:0 0 auto;flex-wrap:wrap}
.bar{display:flex;align-items:center;gap:10px;padding:12px 24px;border-bottom:1px solid var(--line);
 flex-wrap:wrap}
#q{height:32px;width:280px;max-width:52vw;border:1px solid var(--line);border-radius:4px;
 padding:0 8px;background:var(--paper)}
#kind{height:32px;border:1px solid var(--line);border-radius:4px;background:var(--paper);
 padding:0 6px;font-weight:500}
.crumb{font-size:12.5px;color:var(--mut)}
.status{padding:8px 24px;font-size:12.5px;color:var(--grn);border-bottom:1px solid var(--line2);
 min-height:33px}
.status.hint{color:var(--mut)}
.status.err{color:var(--neg)}

.sum{display:flex;align-items:baseline;gap:28px;padding:14px 24px;border-bottom:1px solid var(--line);
 flex-wrap:wrap}
.sum div{display:flex;align-items:baseline;gap:7px}
.sum i{font-style:normal;font-size:12px;color:var(--mut)}
.sum b{font-size:17px;font-weight:700;letter-spacing:-.012em}
.sum .n{margin-left:auto;font-size:12.5px;color:var(--mut)}

.tw{padding:0 0 28px}
table{width:100%;table-layout:fixed;border-collapse:collapse}
th,td{padding:0 12px;height:40px;border-bottom:1px solid var(--line2);
 text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
thead th{position:sticky;top:0;z-index:2;height:34px;background:var(--paper);
 font-size:13px;font-weight:600;color:var(--mut);border-bottom:1px solid var(--line)}
tbody.grp th{height:32px;background:var(--bg);font-size:13px;font-weight:600;color:var(--mut);
 border-bottom:1px solid var(--line)}
tbody.grp div{display:flex;justify-content:space-between;gap:8px}
tr[data-id]{cursor:pointer}
tr[data-id]:hover{background:var(--grn-lt)}
tr[aria-selected="true"]{background:var(--sel);box-shadow:inset 2px 0 0 var(--grn)}
.num{text-align:right}
.a-in{color:var(--grn);font-weight:500}
.a-ex{font-weight:500}
.a-neg{color:var(--neg);font-weight:500}
.tag{display:inline-block;font-size:11px;line-height:17px;padding:0 6px;border:1px solid var(--line);
 border-radius:3px;color:var(--mut)}
.tag.in{border-color:#CFE3D7;background:var(--grn-lt);color:var(--grn-dk)}
.empty td{color:var(--mut);text-align:center;height:64px}
.psel{height:30px;width:132px;border:1px solid var(--line);border-radius:4px;background:var(--paper);
 font-size:12.5px;padding:0 4px}
.lst{display:none}

.panel{width:400px;flex:0 0 400px;background:var(--paper);border-left:1px solid var(--line);
 display:flex;flex-direction:column;min-height:0}
.p-hd{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;
 padding:16px 20px;border-bottom:1px solid var(--line)}
.p-hd h2{font-size:15px;font-weight:700}
.p-amt{font-size:20px;font-weight:700;letter-spacing:-.012em;margin-top:2px}
.p-bd{padding:20px;overflow:auto;flex:1 1 auto}
.p-sub{font-size:12.5px;color:var(--mut);margin-bottom:14px;word-break:break-all}
.f{margin-bottom:14px}
.f label{display:block;font-size:12px;color:var(--mut);margin-bottom:5px}
.f input,.f select,.f textarea{width:100%;height:36px;border:1px solid var(--line);
 border-radius:4px;padding:0 8px;background:var(--paper);font-weight:500}
.f textarea{height:auto;min-height:64px;padding:8px;resize:vertical}
.f input[readonly],.f select[disabled]{background:var(--bg);color:var(--mut)}
.f .err{color:var(--neg);font-size:12.5px;margin-top:6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.src{font-size:12px;color:var(--mut);background:var(--bg);border:1px solid var(--line);
 border-radius:4px;padding:12px;line-height:1.7}
.p-links{display:flex;flex-wrap:wrap;gap:12px;margin-top:14px;font-size:12.5px}
.p-links a{color:var(--grn-dk)}
.sect{margin:0;padding:20px 24px;border-bottom:1px solid var(--line)}
.sect h2{font-size:16px;font-weight:700;margin-bottom:10px}
.sect h3{font-size:14px;font-weight:600;margin:18px 0 8px}
.sect p{margin:0 0 8px;font-size:13.5px}
.sect .kv{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:13px;color:var(--mut)}
.sect .kv b{color:var(--ink);font-weight:600}
.card2{border:1px solid var(--line);border-radius:4px;padding:16px;margin:0 0 12px}
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
 .alloc tr{border:1px solid var(--line);border-radius:4px;padding:10px 12px;margin:0 0 10px}
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
 border:1px solid var(--line);border-radius:4px;background:var(--paper);font-weight:500}
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
 border:1px solid var(--line);border-radius:4px}
.page-body button,.page-body a.btn{
 height:34px;padding:0 12px;margin:6px 6px 0 0;border:1px solid var(--line);
 border-radius:4px;background:var(--paper);font-size:14px;font-weight:600;
 cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}
.page-body .card{border:1px solid var(--line);border-radius:4px;padding:16px;margin:0 0 12px}
.page-body table{border:1px solid var(--line);border-radius:4px;overflow:hidden}
.page-body td,.page-body th{border-bottom:1px solid var(--line2);height:auto;padding:7px 10px}
.page-body a{color:var(--grn-dk)}
@media (max-width:759px){
 .page-body input,.page-body select,.page-body textarea{min-width:0;width:100%;font-size:16px}
 .page-body button,.page-body a.btn{height:44px;width:100%;justify-content:center}
}
.p-ft{display:flex;gap:8px;padding:16px 20px;border-top:1px solid var(--line)}
.p-ft .btn{flex:1}

.btn{height:34px;padding:0 12px;border:1px solid var(--line);border-radius:4px;
 background:var(--paper);font-size:14px;font-weight:600;cursor:pointer;color:var(--ink);
 white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}
.btn:hover{background:var(--bg)}
.btn.primary{background:var(--grn);border-color:var(--grn);color:#fff}
.btn.primary:hover{background:var(--grn-dk)}
.btn[disabled]{opacity:.6;cursor:default}
.icon{width:34px;height:34px;border:1px solid var(--line);border-radius:4px;background:var(--paper);
 cursor:pointer;font-size:14px;line-height:1}
#btn-menu{display:none;font-size:15px}
[hidden]{display:none!important}

@media (max-width:1099px){
 .panel{position:fixed;top:0;right:0;bottom:0;z-index:30;width:min(400px,100%);
  box-shadow:-8px 0 24px rgba(32,37,33,.08)}
}
@media (max-width:759px){
 #btn-menu{display:inline-flex;width:44px;height:44px;align-items:center;justify-content:center}
 .nav{position:fixed;top:0;left:0;bottom:0;z-index:45;transform:translateX(-100%);
  transition:transform .18s ease;border-right:1px solid var(--line)}
 .nav.open{transform:none}
 .nav-mask{display:block;position:fixed;inset:0;z-index:44;background:rgba(32,37,33,.35)}
 .nav-mask[hidden]{display:none!important}
 .tw{display:none}
 .lst{display:block;padding-bottom:24px}
 .panel{top:0;left:0;right:0;width:auto;z-index:60;border-left:0}
 .btn{height:44px;padding:0 14px}
 .icon{width:44px;height:44px}
 .psel{height:44px;width:100%}
 .page-hd{padding:12px 16px 10px;flex-wrap:wrap;gap:8px}
 .page-hd h1{font-size:19px}
 .page-hd .meta{display:none}
 .period{font-size:12.5px}
 .act{margin-left:auto;width:auto}
 .act .btn{height:40px;padding:0 10px;font-size:13.5px}
 .bar{padding:8px 16px;gap:8px}
 #q{flex:1 1 0;min-width:0;width:auto;max-width:none;height:40px}
 #kind{flex:0 0 96px;min-width:0}
 .bar .crumb{display:none}
 #q,#kind,.psel,.f input,.f select,.f textarea,.nav-q input{font-size:16px}
 #kind{height:40px}
 .status{padding:8px 16px;font-size:12.5px}
 .sum{padding:12px 16px;gap:16px}
 .sum .n{margin-left:0}
 .p-bd{padding:16px}
 .p-ft{padding:12px 16px}
 .li{width:100%;min-height:44px;display:flex;align-items:center;gap:8px;padding:9px 16px;
  border:0;border-bottom:1px solid var(--line2);background:var(--paper);text-align:left;cursor:pointer}
 .li .d{font-size:13px;color:var(--mut);white-space:nowrap}
 .li .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px}
 .li .a{margin-left:auto;white-space:nowrap;font-size:15px;font-weight:600}
 .li[aria-selected="true"]{background:var(--sel);box-shadow:inset 2px 0 0 var(--grn)}
 .li.pend{align-items:flex-start;flex-wrap:wrap;white-space:normal;padding-top:12px;padding-bottom:12px}
 .li.pend .psel{margin-top:8px}
 .lg{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;
  background:var(--bg);font-size:12px;font-weight:600;color:var(--mut);border-bottom:1px solid var(--line)}
}
"""

# Only three behaviours, all on top of the existing endpoints.
SCRIPT = """
(function(){
 var main=document.getElementById('main'), nav=document.getElementById('nav'),
     mask=document.getElementById('nav-mask');
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
 function openPanel(id){
  var url=new URL(location.href); url.searchParams.set('row',id);
  fetch(url.toString(),{headers:{'X-Part':'panel'}})
   .then(function(r){return r.text();})
   .then(function(html){
    document.getElementById('panel-slot').innerHTML=html;
    var row=document.querySelector("tr[data-id='"+id+"']");
    if(row) row.setAttribute('aria-selected','true');
   });
 }
 function refreshSummary(){
  var url=new URL(location.href);
  fetch(url.toString()+'&part=summary',{headers:{'X-Part':'summary'}})
   .then(function(r){return r.text();})
   .then(function(html){document.getElementById('sum').outerHTML=html;});
 }
 document.addEventListener('click',function(e){
  if(e.target.id==='p-close'){e.preventDefault();goBack();return;}
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
  post(form.getAttribute('action'),payload).then(function(res){
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
    }else{
     say(slot,'옮겼습니다. 목록과 합계가 갱신되었어요',false);
    }
    if(isSave){refreshSummary();}
    else{
     var next=new URL(location.href);
     next.searchParams.set('msg','옮겼습니다. 목록과 합계가 갱신되었어요');
     location.href=next.toString();
    }
    return;
   }
   say(slot,(body.code||'ERROR')+': '+(body.message||'저장하지 못했어요'),true);
  }).catch(function(){
   say(slot,'요청을 보내지 못했어요. 연결을 확인해 주세요',true);
  });
 });
})();
"""


# ----------------------------------------------------------------- fragments
def _money(value) -> str:
    return MONEY.format(int(value or 0))


def _nav_html(tab_id: str, query: str, kind: str = "", archived: str = "") -> str:
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
    active = [t for t in trips if not t.get("archived") and not t.get("deleted")]
    archived_rows = [t for t in trips if t.get("archived") and not t.get("deleted")]
    unclassified = board._unclassified_rows()

    listed = []
    for trip in active:
        if query and query not in (trip["display_key"] + trip["destination"]):
            continue
        totals = board._trip_totals(trip["tab_id"])
        listed.append(entry(
            board.esc(trip["display_key"]),
            f"/board?{state_query(trip['tab_id'], query, kind, archived)}",
            f"{totals['income']:,}원", trip["tab_id"] == tab_id))
    sections.append(("<h2 class='nav-sec'>여행 목록</h2>",
                     f"<ul class='nav-list' id='trips'>{''.join(listed) or '<li class=\"muted\" style=\"padding:6px 8px\">여행이 없어요</li>'}</ul>"))
    if not query or "분류대기" in query:
        sections.append(("<h2 class='nav-sec'>분류대기</h2>",
                         "<ul class='nav-list'>" + entry(
                             "분류대기",
                             f"/board?{state_query('unclassified', query, kind, archived)}",
                             f"{len(unclassified)}건",
                             tab_id == "unclassified", warn=True) + "</ul>"))
    arch_head = ""
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
    search = (
        "<form class='nav-q' method='get' action='/board'>"
        f"<input type='hidden' name='tab' value='{board.esc(tab_id)}'>"
        f"{f'<input type=hidden name=kind value={board.esc(kind)}>' if kind else ''}"
        "<label class='sr' for='tripq'>여행 검색</label>"
        f"<input id='tripq' name='q' type='search' placeholder='여행 이름·코드'"
        f" value='{board.esc(query)}' autocomplete='off'></form>")
    return (
        "<aside class='nav' id='nav' aria-label='여행 목록'>"
        "<div class='nav-hd'><p class='brand'>숲길여행 법인카드"
        "<small>합성 자료 · Ramp 방향 · Pretendard</small></p></div>"
        f"{search}"
        + "".join(head + body for head, body in sections)
        + arch_head
        + "<p class='nav-ft'>합성 자료만 적용돼요.</p></aside>"
        "<div class='nav-mask' id='nav-mask' hidden></div>")


def _head_html(trip) -> str:
    if trip is None:
        title, period, meta = "여행을 선택해 주세요", "", ""
    elif trip.get("is_unclassified"):
        title = "분류대기"
        period = "여행을 정하지 않은 내역이에요"
        meta = "이 목록을 정리하면 여행 합계가 함께 갱신돼요"
    else:
        title = board.esc(trip["display_key"])
        period = f"<span class='tnum'>{board.esc(trip['starts_on'])}~{board.esc(trip['ends_on'])}</span>"
        meta = (f"<span>작성일 <b>{board.esc(trip.get('prepared_on') or '-')}</b></span>"
                f"<span>담당자 <b>{board.esc(trip.get('prepared_by_name') or '-')}</b></span>"
                f"<span>합계 상태 <b>미확정</b></span>"
                "<span><a href='/trips'>여행 관리</a></span>")
    return (
        "<div class='page-hd'><div>"
        f"<h1>{title}<span class='synth'>{board.SYNTHETIC_MARK}</span></h1>"
        f"<p class='period'>{period}</p>"
        f"<p class='meta'>{meta}</p></div>"
        "<div class='act'>"
        "<a class='btn' href='/import'>카드 가져오기</a>"
        "<a class='btn primary' href='/export'>XLSX 출력</a>"
        "</div></div>")


def _bar_html(query: str, kind: str, tab_id: str, archived: str = "") -> str:
    # One GET form owns the search and the filter, so submitting, refreshing and
    # going back all land on the same URL state.
    return (
        "<form class='bar' method='get' action='/board' id='q-form'>"
        f"<input type='hidden' name='tab' value='{board.esc(tab_id)}'>"
        f"{f'<input type=hidden name=arch value={board.esc(archived)}>' if archived else ''}"
        "<button class='icon' id='btn-menu' type='button' aria-label='여행 목록 열기'"
        " aria-controls='nav' aria-expanded='false'>☰</button>"
        "<label class='sr' for='q'>거래 검색</label>"
        "<input id='q' name='q' type='search' placeholder='용도·내용·메모·예약번호 검색'"
        f" value='{board.esc(query)}' autocomplete='off'>"
        "<label class='sr' for='kind'>구분 필터</label>"
        "<select id='kind' name='kind' onchange='this.form.submit()'>"
        f"<option value=''>전체</option><option value='in'{' selected' if kind == 'in' else ''}>수입만</option>"
        f"<option value='ex'{' selected' if kind == 'ex' else ''}>지출만</option></select>"
        "<button class='btn' type='submit' id='q-go'>검색</button>"
        + (f"<a class='btn' id='q-clear' href='/board?{state_query(tab_id)}'>지우기</a>"
           if (query or kind) else "")
        + "</form>")


def _summary_html(incomes, expenses) -> str:
    income = sum(board._shown_amount(r) for r in incomes)
    expense = sum(board._shown_amount(r) for r in expenses)
    return (
        f"<div class='sum tnum' id='sum'><div><i>수입</i><b>{_money(income)}</b></div>"
        f"<div><i>지출</i><b>{_money(expense)}</b></div>"
        f"<div><i>차액</i><b>{_money(income - expense)}</b></div>"
        f"<span class='n'>수입 {len(incomes)}건 · 지출 {len(expenses)}건</span></div>")


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


def _table_html(rows, *, kind, selected, unclassified, move_back="/board") -> str:
    if not rows:
        return ("<tbody class='grp'><tr><th scope='colgroup'>"
                f"{'수입' if kind == 'income' else '지출'}</th></tr></tbody>"
                "<tbody><tr class='empty'><td colspan='6'>"
                f"{'수입 내역이 없어요' if kind == 'income' else '지출 내역이 없어요'}"
                "</td></tr></tbody>")
    body = []
    for row in rows:
        rid = row["row_id"]
        amount = board._shown_amount(row)
        note = row.get("operator_note") or ""
        move = ""
        if unclassified:
            move = (
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
                "<button class='btn' type='submit'>이동</button></form>")
        body.append(
            f"<tr data-id='{board.esc(rid)}'"
            f"{' aria-selected=\"true\"' if rid == selected else ''}>"
            f"<td class='tnum'>{board.esc(board._shown_date(row))}</td>"
            f"<td><span class='tag{' in' if _row_kind_meter(row) == '수입' else ''}'>"
            f"{_row_kind_meter(row)}</span></td>"
            f"<td>{board.esc(row.get('item') or _income_kind_label(row))}</td>"
            f"<td>{board.esc(row.get('description') or row.get('customer_name') or '-')}</td>"
            f"<td>{board.esc(note or row.get('source_merchant') or '')}</td>"
            f"<td class='num tnum {_row_amount_class(row)}'>{_money(amount)}</td>"
            f"</tr>" if not move else
            f"<tr data-id='{board.esc(rid)}'"
            f"{' aria-selected=\"true\"' if rid == selected else ''}>"
            f"<td class='tnum'>{board.esc(board._shown_date(row))}</td>"
            f"<td><span class='tag'>{_row_kind_meter(row)}</span></td>"
            f"<td>{board.esc(row.get('item') or '-')}</td>"
            f"<td>{board.esc(row.get('description') or '-')}</td>"
            f"<td>{move}</td>"
            f"<td class='num tnum {_row_amount_class(row)}'>{_money(amount)}</td>"
            f"</tr>")
    return f"<tbody>{''.join(body)}</tbody>"


def _tables_html(incomes, expenses, *, selected, unclassified, move_back="/board") -> str:
    head = (
        "<div class='tw'><table id='tbl'>"
        "<caption class='sr'>거래 명역역. 수입은 위, 지출은 아래에 있습니다.</caption>"
        "<colgroup><col style='width:122px'><col style='width:64px'><col style='width:106px'>"
        "<col><col style='width:22%'><col style='width:132px'></colgroup>"
        "<thead><tr><th scope='col'>날짜</th><th scope='col'>구분</th><th scope='col'>항목</th>"
        "<th scope='col'>용도</th><th scope='col' id='h5'>메모</th>"
        "<th scope='col' class='num'>금액</th></tr></thead>")
    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    groups = (
        f"<tbody class='grp'><tr><th scope='colgroup' colspan='5'>수입</th>"
        f"<th class='num'>{_money(income_total)}</th></tr></tbody>"
        + _table_html(incomes, kind="income", selected=selected, unclassified=False)
        + f"<tbody class='grp'><tr><th scope='colgroup' colspan='5'>지출</th>"
        f"<th class='num'>{_money(expense_total)}</th></tr></tbody>"
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
                f"<select class='psel' name='display_tab_id'>"
                f"{_trip_options('', '분류대기(여행 미정)')}</select>"
                "<button class='btn' type='submit'>이동</button></form>")
        cls = "li pend" if unclassified else "li"
        return (
            f"<button class='{cls}' type='button' data-id='{board.esc(rid)}'"
            f"{' aria-selected=\"true\"' if rid == selected else ''}>"
            f"<span class='d tnum'>{board.esc(board._shown_date(row))}</span>"
            f"<span class='t'>{board.esc(row.get('item') or _income_kind_label(row))}"
            f" {board.esc(row.get('description') or row.get('customer_name') or '')}</span>"
            f"<span class='a tnum {_row_amount_class(row)}'>"
            f"{_money(board._shown_amount(row))}</span></button>{move}")

    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    return (
        "<div class='lst'>"
        f"<p class='lg'><span>수입</span><span class='tnum'>{_money(income_total)}</span></p>"
        f"{''.join(item(r) for r in incomes) or '<p class=\"muted\" style=\"padding:12px 16px\">수입 내역이 없어요</p>'}"
        f"<p class='lg'><span>지출</span><span class='tnum'>{_money(expense_total)}</span></p>"
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

    fields.append("<div class='grid2'>")
    fields.append(text_field("occurred_on", "거래 날짜 (고정)",
                             board._shown_date(row), ro="occurred_on" in fixed))
    fields.append(text_field("amount_krw", "거래 금액 (고정)", f"{amount:,}",
                             ro="amount_krw" in fixed))
    fields.append("</div>")
    fields.append(text_field("reservation_no", "예약번호 (고정)",
                             row.get("reservation_no", ""), ro=True))

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
    return (
        "<aside class='panel' id='panel' aria-label='거래 상세 편집 패널'>"
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
        f"<p class='p-sub'>{board.esc(row.get('source_event_id') or row['row_id'])}"
        f" · revision {rev} · {board.esc(row.get('source_kind') or '')}</p>"
        f"{''.join(fields)}{note}"
        "<p class='src'>원천 날짜·금액·예약번호는 읽기 전용이에요. 여행·항목·용도·메모는 "
        "운영자가 정합니다. 실제 AI 연결 전에는 규칙 초안이 원천을 바꾸지 않습니다.</p>"
        f"<div class='p-links'>{' · '.join(x for x in links if x)}</div>"
        "</div>"
        "<div class='p-ft'>"
        "<button class='btn primary' type='submit'>저장</button>"
        f"<a class='btn' id='p-cancel' href='{board.esc(back)}'>취소</a>"
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


def shell(title: str, *, tab_id: str, heading: str, period: str = "",
          meta: str = "", body: str, query: str = "", kind: str = "",
          archived: str = "", aside: str = "") -> str:
    """The shared chrome for every screen, with the view state in the links."""
    state = state_query(tab_id, query, kind, archived)
    back = f"/board?{state}"
    main = (
        f"<main class='main' id='main' tabindex='-1' data-base='{board.esc(back)}'>"
        "<div class='page-hd'><div>"
        f"<h1>{heading}<span class='synth'>{board.SYNTHETIC_MARK}</span></h1>"
        + (f"<p class='period'>{period}</p>" if period else "")
        + (f"<p class='meta'>{meta}</p>" if meta else "")
        + "</div><div class='act'>"
        "<a class='btn' href='/import'>카드 가져오기</a>"
        "<a class='btn primary' href='/export'>XLSX 출력</a>"
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


def page(tab_id: str, query: str = "", kind: str = "", selected: str = "",
         error: str = "", message: str = "", archived: str = "",
         draft: dict = None, back: str = "") -> str:
    """The main ledger screen in the new design."""
    if _STORE_missing():
        return board.layout("웹 장부", "<div class='body'><p>저장소가 연결되지 않았어요.</p></div>")
    trip = _selected_trip(tab_id)
    if tab_id == "unclassified":
        incomes = [r for r in board._income_rows() if r.get("display_tab_id") is None]
        expenses = board._unclassified_rows()
    elif trip is None:
        incomes = expenses = []
    else:
        incomes = [r for r in board._income_rows() if r.get("display_tab_id") == tab_id]
        expenses = [r for r in board._expense_rows() if r.get("display_tab_id") == tab_id]
    if kind == "in":
        expenses = []
    elif kind == "ex":
        incomes = []
    if query:
        def keep(row):
            blob = " ".join(str(row.get(key) or "") for key in (
                "item", "description", "operator_note", "reservation_no",
                "source_merchant", "customer_name"))
            return query in blob
        incomes = [r for r in incomes if keep(r)]
        expenses = [r for r in expenses if keep(r)]

    unclassified = tab_id == "unclassified"
    status = ""
    if error:
        status = f"<p class='status err' id='status' role='alert'>{board.esc(error)}</p>"
    elif message:
        status = (f"<p class='status' id='status' role='status'>"
                  f"{board.esc(message)}</p>")
    else:
        status = ("<p class='status hint' id='status' role='status' aria-live='polite'>"
                  "행을 누르면 편집할 수 있어요"
                  "</p>")
    back = back or ("/board?" + state_query(tab_id, query, kind, archived))
    panel = ""
    if selected:
        panel = panel_part(selected, back=back, error=error, message=message,
                           draft=draft or {})
    main = (
        f"<main class='main' id='main' tabindex='-1' data-base='{board.esc(back)}'>"
        f"{_head_html(trip)}"
        f"{_bar_html(query, kind, tab_id, archived)}{status}"
        f"{_summary_html(incomes, expenses)}"
        f"{_tables_html(incomes, expenses, selected=selected, unclassified=unclassified, move_back=back)}"
        f"{_mobile_html(incomes, expenses, selected=selected, unclassified=unclassified, move_back=back)}"
        "</main>")
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


def summary_part(tab_id: str, kind: str = "") -> str:
    if _STORE_missing():
        return ""
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
    return _summary_html(incomes, expenses)


def _STORE_missing() -> bool:
    return getattr(board, "_STORE", None) is None


def render(page_html: str, title: str = "웹 장부") -> str:
    """Wrap a design fragment in the document with the design stylesheet."""
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{board.esc(title)}</title><style>{STYLE}</style></head>"
        f"<body>{page_html}<script>{SCRIPT}</script></body></html>")
