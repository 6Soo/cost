"""Owner-only, COST-local flight passenger candidate review; reservation reads only."""

import json
import hashlib
import unicodedata
import os
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from app import flight_passenger_matching, reservation_authority

ROUTES = ('/flight-passengers', '/api/flight-passengers/candidates', '/api/flight-passengers/assign', '/api/flight-passengers/name-search')
FEATURE_FLAG = 'WEBLEDGER_FLIGHT_PASSENGER_MATCHING'
DB_ENV = 'WEBLEDGER_FLIGHT_PASSENGER_DB'


def owns_route(path):
    return path in ROUTES


def enabled():
    return os.environ.get(FEATURE_FLAG) == '1'


def _db_path():
    value = os.environ.get(DB_ENV, '').strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve(strict=False) if path.is_absolute() else None


def _send(handler, body, status=200):
    handler._send_json(body, status)


def _escape_csrf_json(csrf):
    # Keep untrusted token text inside the script string, even when it contains
    # an HTML script terminator.
    return json.dumps(str(csrf or ''), ensure_ascii=True).replace('<', r'\u003c')


def _legacy_page(csrf):
    token = _escape_csrf_json(csrf)
    return """<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>항공권 참가자 후보</title>
<style>
:root{--bg:#F8FAFC;--paper:#FFFFFF;--ink:#0F172A;--mut:#475569;--line:#E2E8F0;--line2:#F1F5F9;--line-strong:#D0D5DD;--hover:#F8FAFC;--focus:#2266F5;--sel:#ECF5EF;--grn:#1C7A52;--warn:#B54708;--neg:#B42318;--bad:#B42318}
@media(prefers-color-scheme:dark){:root{--bg:#0F172A;--paper:#1E293B;--ink:#F8FAFC;--mut:#94A3B8;--line:#334155;--line2:#334155;--line-strong:#475569;--hover:#334155;--focus:#2266F5;--sel:#1E3A5F;--grn:#86EFAC;--warn:#FDBA74;--neg:#FCA5A5;--bad:#FCA5A5}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,"Malgun Gothic",Apple SD Gothic Neo,sans-serif;word-break:keep-all;-webkit-text-size-adjust:100%}
h1,h2,p{margin:0}
#flight-passenger-page{max-width:760px;margin:32px auto;padding:0 16px;color:var(--ink)}
@media(max-width:390px){#flight-passenger-page{margin:20px 12px;padding:0}}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
#flight-passenger-page button,#flight-passenger-page input{font:inherit;color:inherit}
#flight-passenger-page label{display:block;font-size:13px;color:var(--mut);margin:0 0 6px;font-weight:500}
#flight-passenger-page form{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:14px 14px 10px}
#flight-passenger-page form label{display:flex;flex-direction:column;align-items:stretch;gap:6px;min-width:0;flex:1 1 220px;margin:0;padding:0;font-size:13px;color:var(--ink);font-weight:500;white-space:normal}
#flight-passenger-page input[name='booking_ref'],#flight-passenger-page input[name='tour_id']{width:100%;min-width:0;height:40px;border:1px solid var(--line-strong);border-radius:7px;padding:0 9px;background:var(--paper);font-weight:500;font-size:14px;color:var(--ink)}
#flight-passenger-page input:focus{border-color:var(--focus)!important;box-shadow:0 0 0 3px rgba(34,102,245,.12);outline:none}
#flight-passenger-page button{min-height:36px;padding:0 12px;border:1px solid var(--line-strong);border-radius:7px;background:var(--paper);font-size:14px;font-weight:600;cursor:pointer;color:var(--ink);display:inline-flex;align-items:center;justify-content:center;white-space:nowrap}
#flight-passenger-page button:hover{background:var(--hover)}
#flight-passenger-page button[type='button'][disabled]{opacity:.45;cursor:default}
#flight-passenger-page section#results{margin-top:18px}
#flight-passenger-page article{border:1px solid var(--line);border-radius:8px;background:var(--paper);padding:14px;margin:0 0 12px;overflow:hidden}
#flight-passenger-page article h2{font-size:15px;font-weight:700;margin:0 0 6px;color:var(--ink)}
#flight-passenger-page article p{font-size:13px;color:var(--mut);margin:4px 0;line-height:1.45}
#flight-passenger-page article label{display:flex;align-items:center;gap:8px;min-height:44px;margin:0;padding:6px 8px;font-size:13.5px;color:var(--ink);cursor:pointer;white-space:normal;border-radius:6px}
#flight-passenger-page article label:hover{background:var(--hover)}
#flight-passenger-page article input[type='radio']{accent-color:var(--grn);flex:0 0 auto;width:18px;height:18px;margin:0}
#flight-passenger-page article .empty{color:var(--mut);font-size:13.5px;margin:6px 0}
#flight-passenger-page article .warning{color:var(--warn);font-size:13px;font-weight:600;margin:4px 0}
#status[role='status']{min-height:24px;font-size:13px;color:var(--mut);margin:10px 0 6px}
#status[role='status']:not(:empty){font-weight:500;color:var(--ink)}
@media(max-width:375px){#flight-passenger-page form{flex-direction:column;align-items:stretch;padding:12px}#flight-passenger-page form label{margin:0 0 4px;font-size:12px}#flight-passenger-page article{padding:12px}#flight-passenger-page{padding:0 10px}}
</style>
""" + "</head><body><main id='flight-passenger-page'>" + """
<h1>항공권 참가자 연결</h1><p>항공권에 기재된 영문 이름과 예약 명단의 참가자를 비교합니다. 선택한 연결은 COST에만 저장되며, 실제 탑승 여부나 예약 명단은 변경되지 않습니다.</p>
<form id='search' aria-label='항공권 참가자 연결 검색'><label for='f-booking'>항공권 예약번호<input id='f-booking' name='booking_ref' required autocomplete='off'></label><label for='f-tour'>예약 시스템 여행 ID<input id='f-tour' name='tour_id' required autocomplete='off'></label><button id='search-submit' type='submit'>연결 후보 찾기</button></form>
<p id='status' role='status' aria-live='polite'></p><section id='results' aria-label='후보 결과'></section>
</main><script>
const csrf=""" + token + """;
const form=document.querySelector('#search'), status=document.querySelector('#status'), root=document.querySelector('#results'), searchButton=document.querySelector('#search-submit');
status.textContent='항공권 예약번호와 여행 ID를 입력해 연결할 참가자를 찾아보세요.';
const apiMessage=code=>({'VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND':'확인된 항공권 예약 근거를 찾지 못했습니다. 예약번호를 확인해 주세요.','RESERVATION_AUTHORITY_UNAVAILABLE':'예약 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.','RESERVATION_AUTHORITY_UNAUTHORIZED':'예약 서비스 인증이 만료됐습니다. 관리자에게 문의해 주세요.','PASSENGER_ASSIGNMENT_ALREADY_CONFIRMED':'이미 확인한 연결과 달라 저장할 수 없습니다. 기존 연결을 확인해 주세요.','PASSENGER_CANDIDATE_REQUIRED':'후보를 다시 조회하고 한 명을 선택해 주세요.','INVALID_VALUE':'입력한 예약번호와 여행 ID를 확인해 주세요.','FEATURE_DISABLED':'현재 사용할 수 없는 기능입니다.','STORE_UNAVAILABLE':'자료를 불러올 수 없습니다. 관리자에게 문의해 주세요.'}[code]||'요청을 처리하지 못했습니다. 입력을 확인한 뒤 다시 시도해 주세요.');
form.addEventListener('submit',async event=>{event.preventDefault();root.replaceChildren();searchButton.disabled=true;status.textContent='항공권과 예약 명단을 대조하는 중입니다.';
const values=new FormData(form), booking_ref=String(values.get('booking_ref')||''), tour_id=String(values.get('tour_id')||'');
try{const response=await fetch('/api/flight-passengers/candidates?booking_ref='+encodeURIComponent(booking_ref)+'&tour_id='+encodeURIComponent(tour_id));
const data=await response.json();if(!response.ok)throw Error(apiMessage(data.code));
for(const old of data.stale_assignments||[]){const notice=document.createElement('p');notice.className='warning';notice.textContent='이전 연결의 근거가 변경됐습니다. 최신 자료를 확인하고 다시 선택해 주세요.';root.append(notice)}
if(data.cancellation_status==='CANCELLED'||data.cancellation_status==='CONFLICT'||data.evidence_conflict){const warning=document.createElement('p');warning.className='warning';warning.textContent=data.cancellation_status==='CANCELLED'?'항공권 취소가 확인되어 연결할 수 없습니다. 예약 상태를 확인해 주세요.':'항공권과 예약 자료가 일치하지 않아 연결할 수 없습니다. 원본을 확인해 주세요.';root.append(warning)}
for(const passenger of data.passengers||[]){const article=document.createElement('article'), title=document.createElement('h2');
if(passenger.assignment){const saved=document.createElement('p');saved.className=passenger.assignment.stale?'warning':'success';saved.textContent=passenger.assignment.stale?'이전 연결의 근거가 변경됐습니다. 최신 자료를 확인하고 다시 선택해 주세요.':'저장된 COST 연결: '+(passenger.assignment.candidate?.name_kr||'참가자')+' · 사용자가 확인했습니다.';article.append(saved)}
for(const old of passenger.stale_assignments||[]){const notice=document.createElement('p');notice.textContent='저장된 COST 연결 이력이 있지만 원본이 바뀌었거나 현재 승객 제안과 일치하지 않아 다시 확인해야 합니다.';article.append(notice)}
const stateLabel=({EXACT_CANDIDATE:'후보 1명',AMBIGUOUS:'복수 후보',UNMATCHED:'후보 없음',CANCELLED_EVIDENCE:'취소 확인',CONFLICTING_EVIDENCE:'자료 충돌'})[passenger.status]||'상태 확인 필요';title.textContent=passenger.passenger_name_en+' · '+stateLabel;article.append(title);
if(!passenger.candidates.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='연결할 참가자 후보가 없습니다. 예약 명단과 영문 이름을 확인해 주세요. 새 참가자를 자동 생성하지 않습니다.';article.append(empty)}
if(passenger.candidates.length>1){const warning=document.createElement('p');warning.className='warning';warning.textContent='같은 영문 이름의 후보가 '+passenger.candidates.length+'명입니다. 예약 정보를 확인한 뒤 한 명을 선택해 주세요.';article.append(warning)}
for(const [index,candidate] of (passenger.cancellation_status==='NONE'&&!passenger.evidence_conflict?passenger.candidates:[]).entries()){const label=document.createElement('label'), radio=document.createElement('input');radio.type='radio';radio.name=passenger.proposal_id;radio.value=candidate.reference_id;
const kind=candidate.kind==='lead'?'예약자':candidate.kind==='companion'?'동행인':'안내자';
label.append(radio,document.createTextNode(' '+(passenger.candidates.length>1?kind+' 후보 '+(index+1):kind)+' · '+candidate.name_kr));article.append(label)}
if(passenger.candidates.length&&passenger.cancellation_status==='NONE'&&!passenger.evidence_conflict){const button=document.createElement('button');button.type='button';button.textContent='선택한 참가자를 COST에 연결';button.addEventListener('click',async()=>{const selected=article.querySelector('input:checked');if(!selected){status.textContent='연결할 참가자를 먼저 선택해 주세요.';return}button.disabled=true;
try{const saved=await fetch('/api/flight-passengers/assign',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({booking_ref,tour_id,proposal_id:passenger.proposal_id,candidate_reference_id:selected.value})});const result=await saved.json();if(!saved.ok)throw Error(apiMessage(result.code));const confirmation=document.createElement('p');confirmation.className='success';confirmation.setAttribute('role','status');confirmation.textContent='COST 내부 연결을 저장했습니다. 실제 탑승 여부는 확인되지 않았습니다.';article.append(confirmation);button.disabled=true}
catch(error){status.textContent=error.message;button.disabled=false}});article.append(button)}root.append(article)}status.textContent=(data.passengers||[]).length?'후보를 확인했습니다. 연결할 참가자를 직접 선택해 주세요.':'이 예약에서 확인할 탑승자 정보를 찾지 못했습니다. 예약번호와 여행 ID를 확인해 주세요.'}
catch(error){status.textContent=error.message}finally{searchButton.disabled=false}});
</script></body></html>"""



def _page(csrf):
    token = _escape_csrf_json(csrf)
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>항공권 예약 확인</title>
<style>
:root{--bg:#f8fafc;--paper:#fff;--ink:#0f172a;--mut:#475569;--line:#e2e8f0;--hover:#f1f5f9;--focus:#2563eb;--good:#047857;--warn:#a16207}
@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--paper:#1e293b;--ink:#f8fafc;--mut:#cbd5e1;--line:#334155;--hover:#334155;--focus:#93c5fd;--good:#6ee7b7;--warn:#fbbf24}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,"Malgun Gothic",sans-serif}
#flight-booking-page{max-width:1080px;margin:32px auto;padding:0 22px 64px}
#flight-booking-page h1{font-size:26px;margin:0 0 6px}#flight-booking-page h2{font-size:17px;margin:0 0 12px}
#flight-booking-page p{margin:0 0 14px}.fb-muted{color:var(--mut)}.fb-panel{border:1px solid var(--line);border-radius:14px;background:var(--paper);padding:20px;margin-top:18px}
#flight-booking-page form{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}#flight-booking-page label{display:grid;gap:6px;flex:1 1 250px;font-weight:650}
#flight-booking-page input{font:inherit;min-height:44px;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--paper);color:var(--ink);min-width:0;width:100%}
#flight-booking-page button{font:inherit;min-height:44px;padding:10px 16px;border:1px solid var(--line);border-radius:9px;background:var(--hover);color:var(--ink);font-weight:650;cursor:pointer}
#flight-booking-page button:disabled{opacity:.55;cursor:wait}#flight-booking-page button:focus-visible,#flight-booking-page input:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.fb-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.fb-field{min-width:0}.fb-field small{display:block;color:var(--mut)}.fb-field strong{overflow-wrap:anywhere}
.fb-status{font-size:12px;display:inline-block;border:1px solid var(--line);border-radius:100px;padding:3px 9px;margin:0 0 10px;color:var(--mut)}
.fb-ticket{border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:14px;background:var(--paper)}
.fb-ticket h3{font-size:17px;margin:0 0 12px;overflow-wrap:anywhere}.fb-ticket p{overflow-wrap:anywhere}.fb-ticket summary,.fb-ticket a{display:block;min-height:44px;padding:10px 0}.fb-section{border-top:1px solid var(--line);margin-top:15px;padding-top:14px}
.fb-note{border-left:3px solid var(--warn);padding:9px 12px;background:var(--hover);color:var(--ink);font-size:13px}
.fb-date-row{border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0;background:var(--paper)}
#fb-status{min-height:24px;margin-top:12px}#fb-results{margin-top:16px}
@media(max-width:600px){#flight-booking-page{margin:18px auto;padding:0 12px 36px}.fb-grid{grid-template-columns:minmax(0,1fr)}.fb-panel{padding:14px}#flight-booking-page form{display:grid}#flight-booking-page h1{font-size:22px}}

/* Flight reservation detail: hero, evidence summary and compact directional itinerary. */
.fb-ticket{border:0;background:transparent;padding:0;margin-top:22px;container-type:inline-size}
.fb-hero{position:relative;isolation:isolate;overflow:hidden;border-radius:22px 22px 0 0;padding:25px 28px 32px;background:linear-gradient(115deg,#f8fbff 8%,#deecfe 100%);color:#142441}
.fb-hero .fb-status{background:#fff;color:#1261bb;border-color:#dceafa;padding:7px 12px}
.fb-eyebrow{font-size:14px;font-weight:650;color:#66768e}
.fb-ticket .fb-hero h3{font-size:clamp(18px,2.9vw,28px);line-height:1.3;margin:3px 0 10px;padding-right:55px;position:relative;z-index:1}
.fb-hero-subtitle{color:#63768e;position:relative;z-index:1}
.fb-hero-plane{position:absolute;right:35px;top:38px;font-size:96px;line-height:1;color:#92bdec;transform:rotate(-20deg);opacity:.45;pointer-events:none}
.fb-summary{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:0;border:1px solid var(--line);border-radius:0 0 18px 18px;background:var(--paper);box-shadow:0 12px 30px #173c6710;padding:10px 20px}
.fb-summary-item{grid-column:span 2;display:flex;align-items:center;gap:13px;min-width:0;padding:18px 12px}
.fb-summary-item:nth-child(-n+2){grid-column:span 3;border-bottom:1px solid var(--line)}
.fb-summary-copy{min-width:0}.fb-summary-copy small{display:block;color:var(--mut);font-size:13px}.fb-summary-copy strong{display:block;font-size:clamp(13px,1.65vw,18px);line-height:1.5;overflow-wrap:anywhere}.fb-summary-detail{display:block;color:var(--mut);font-size:12px}
.fb-icon{display:grid;place-items:center;flex:0 0 43px;width:43px;height:43px;border-radius:50%;background:#e7f2ff;color:#0963c4;font-size:21px;font-weight:800}
.fb-summary-item:nth-child(2) .fb-icon{background:#eeeafe;color:#5551ae}.fb-summary-item:nth-child(3) .fb-icon{background:#e0f7ed;color:#087a59}.fb-summary-item:nth-child(4) .fb-icon{background:#fff0e2;color:#bb691d}.fb-summary-item:nth-child(5) .fb-icon{background:#edf0f4;color:#586477}
.fb-itinerary{border:0;margin-top:20px}.fb-heading{display:flex;align-items:center;gap:14px;margin:0 0 14px}.fb-heading h2{font-size:21px!important;margin:0!important}.fb-heading p{margin:0!important}.fb-heading-icon{display:grid;place-items:center;font-size:25px;color:#126bc7;background:#e3f2ff;width:48px;height:48px;border-radius:15px}
.fb-flight-card{border:1px solid var(--line);background:var(--paper);border-radius:17px;padding:14px 18px 20px;margin:14px 0;box-shadow:0 6px 22px #1835560a;min-width:0}
.fb-flight-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-radius:12px;padding:10px 13px;background:linear-gradient(90deg,#e5f2ff,#f4f9fe)}
.fb-flight-badge{display:grid;place-items:center;flex:0 0 40px;height:40px;border-radius:11px;background:#c2e0ff;color:#0d65c1;font-size:26px}
.fb-flight-title{font-size:19px}.fb-flight-date{font-weight:600;color:var(--mut)}.fb-flight-number{margin-left:auto;border-radius:30px;background:#d7ebff;color:#0862be;padding:5px 14px;font-weight:750}
.fb-return .fb-flight-bar{background:linear-gradient(90deg,#e2f7ee,#f2fcf8)}.fb-return .fb-flight-badge{background:#aeebd3;color:#05734e}.fb-return .fb-flight-number{background:#d7f4e8;color:#087f60}
.fb-route{display:grid;grid-template-columns:minmax(0,1fr) minmax(60px,.5fr) minmax(0,1fr);gap:10px;align-items:center;padding:22px 16px}
.fb-route-stop{text-align:center;min-width:0}.fb-route-stop small{display:block;color:var(--mut)}.fb-route-stop strong{display:block;font-size:clamp(16px,2.3vw,24px);line-height:1.4;overflow-wrap:anywhere}.fb-airport-code{display:inline-block;background:var(--hover);border-radius:25px;padding:3px 16px;margin-top:6px;font-weight:700}.fb-route-arrow{font-size:29px;text-align:center;color:#2186db;position:relative}.fb-return .fb-route-arrow{color:#19a27c}
.fb-flight-facts{border-top:1px solid var(--line);padding-top:15px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.fb-flight-facts .fb-field{padding:0 8px;border-right:1px solid var(--line)}.fb-flight-facts .fb-field:last-child{border:0}.fb-flight-facts .fb-field strong{font-size:15px}
@media(prefers-color-scheme:dark){.fb-hero{background:linear-gradient(110deg,#193452,#203f65);color:var(--ink)}.fb-hero .fb-status{background:#254866;color:#c9e3ff}.fb-hero-subtitle,.fb-eyebrow{color:#c5d8ed}.fb-summary,.fb-flight-card{box-shadow:none}.fb-flight-bar{background:#213f5d}.fb-return .fb-flight-bar{background:#20493f}.fb-flight-number{background:#2d557d;color:#c6e4ff}.fb-return .fb-flight-number{background:#205c4c;color:#b9efdf}.fb-icon{background:#234e7b;color:#a7d9ff}}
@media(max-width:600px){.fb-hero{padding:18px 16px 22px}.fb-hero-plane{font-size:58px;right:9px;top:47px}.fb-summary{grid-template-columns:repeat(2,minmax(0,1fr));padding:7px}.fb-summary-item{grid-column:span 2!important;padding:10px 9px;border-bottom:1px solid var(--line)}.fb-summary-item:last-child{border:0}.fb-icon{width:37px;height:37px;flex-basis:37px}.fb-flight-card{padding:9px 10px 15px}.fb-flight-bar{gap:8px}.fb-flight-title{font-size:16px}.fb-flight-date{font-size:12px}.fb-flight-number{padding:4px 9px}.fb-route{grid-template-columns:minmax(0,1fr) 40px minmax(0,1fr);gap:4px;padding:17px 3px}.fb-route-arrow{font-size:23px}.fb-flight-facts{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.fb-flight-facts .fb-field:nth-child(even){border:0}}
.fb-flight-number,.fb-airport-code{box-sizing:border-box;max-width:100%;overflow-wrap:anywhere}
.fb-heading>div{min-width:0;overflow-wrap:anywhere}.fb-heading-icon{flex-shrink:0}
@container(max-width:280px){.fb-route{grid-template-columns:minmax(0,1fr);padding:12px 0}.fb-route-arrow{transform:rotate(90deg)}.fb-summary{padding:4px}.fb-summary-item{padding:8px 2px;gap:6px}.fb-flight-facts{grid-template-columns:minmax(0,1fr)}.fb-flight-facts .fb-field{border:0}.fb-flight-bar{padding:7px;gap:5px}.fb-flight-number{margin-left:0}.fb-hero{padding:14px 10px}.fb-hero h3{padding-right:0!important}.fb-heading{gap:8px}}
</style></head><body><main id="flight-booking-page">
<h1>항공권 예약 확인</h1><p class="fb-muted">탑승객 이름으로 항공권 예약과 연결된 카드 결제 내역을 확인합니다.</p>
<p class="fb-muted">이 조회는 예약·결제나 실제 탑승 여부를 확정하지 않습니다.</p>
<section class="fb-panel" aria-label="항공권 조회">
<form id="fb-search"><label for="fb-name">탑승객 이름<input id="fb-name" name="name" placeholder="영문 또는 한글 이름" autocomplete="off" required maxlength="100"></label><button type="submit" id="fb-submit">예약 조회</button></form>
<p class="fb-muted" id="fb-status" role="status" aria-live="polite">이름을 입력해 예약 내역을 조회해 주세요.</p></section>
<section id="fb-results" aria-label="예약 조회 결과"></section><button id="fb-more" type="button" hidden>예약 더 보기</button></main>
<script>
const CSRF=__CSRF__;
const form=document.getElementById('fb-search'),resultRoot=document.getElementById('fb-results'),status=document.getElementById('fb-status'),submit=document.getElementById('fb-submit');
const more=document.getElementById('fb-more');let nextOffset=null,sourceRevision=null,searchName='';
function text(parent,tag,value,klass){const e=document.createElement(tag);if(klass)e.className=klass;e.textContent=String(value??'');parent.append(e);return e}
function field(parent,label,value){const wrap=document.createElement('div');wrap.className='fb-field';text(wrap,'small',label);text(wrap,'strong',value||'확인되지 않음');parent.append(wrap)}
function manualDateFilter(parent,confirmedDay=null,basis='EXPLICIT_LABEL'){
const details=document.createElement('details');details.className='fb-date-filter';parent.append(details);
text(details,'summary',confirmedDay?(basis==='FIRST_RECEIVED'?'최초 메일 수신일의 카드 거래 전체 조회':'예약 시각의 한국 날짜로 카드 거래 전체 조회'):'직접 지정한 날짜로 카드 원행 조회');
text(details,'p',confirmedDay?(basis==='FIRST_RECEIVED'?'별도 예약일이 없어 보관된 인증 메일의 최초 수신일을 예약일 기준으로 사용합니다. 결제 연결은 미확정입니다.':'원본 예약 시각과 시간대를 한국 시간으로 환산한 날짜입니다. 결제 연결이 확정된 것은 아닙니다.'):'예약일이나 결제 연결이 확정된 것은 아닙니다.','fb-note');
text(details,'p','해당 날짜의 모든 카드 원행을 조회합니다. 취소·환불·중복·기존 분류를 제외하지 않으며 이 예약과의 연결 여부는 판정하지 않습니다.','fb-muted');
const filter=document.createElement('form'),label=text(filter,'label','조회 날짜 (직접 지정 필터)');
const dateInput=document.createElement('input');dateInput.type='date';dateInput.required=true;dateInput.min='2000-01-01';dateInput.max='2100-12-31';label.append(dateInput);
const search=text(filter,'button','지정 날짜 원행 조회');search.type='submit';details.append(filter);
const note=text(details,'p','날짜를 직접 지정해 조회해 주세요.','fb-date-status');note.setAttribute('role','status');note.setAttribute('aria-live','polite');
const rows=document.createElement('div');details.append(rows);
const next=text(details,'button','카드 원행 더 보기');next.type='button';next.hidden=true;
let activeDay='',cursor=null,revision=null;
const render=tx=>{
 const row=document.createElement('article');row.className='fb-date-row';text(row,'h3',tx.merchant||'가맹점 미확인');
 const grid=document.createElement('div');grid.className='fb-grid';row.append(grid);
 for(const [key,title] of [['approval_date','이용일·원본 시각'],['approval_number','승인번호'],['transaction_direction','원행 거래 구분'],['transaction_kind','원행 거래 유형'],['classification_state','기존 분류 상태'],['trip_id','원행 여행 ID'],['display_tab_id','기존 표시 여행 ID'],['item','비용 항목']])field(grid,title,tx[key]);
 field(grid,'원화 금액',tx.amount_krw==null?null:String(tx.amount_krw)+'원');
 field(grid,'외화 금액·통화',[tx.foreign_amount,tx.foreign_currency].filter(v=>v!=null&&v!=='').join(' '));
 const protections=[];if(tx.duplicate_of)protections.push('중복 원행');if(tx.conflict_reason)protections.push('원본 충돌');if(tx.parse_error)protections.push('원본 오류');
 if(protections.length)text(row,'p',protections.join(' · '),'fb-note');
 rows.append(row);
};
async function load(reset){
 if(reset){activeDay=dateInput.value;cursor=null;revision=null;rows.replaceChildren();next.hidden=true}
 const requestedDay=activeDay;search.disabled=true;next.disabled=true;note.textContent='카드 원행을 읽고 있습니다.';
 try{
  const query=new URLSearchParams({date:requestedDay});if(cursor){query.set('cursor',cursor);query.set('revision',revision)}
  const response=await fetch('/api/cards/transactions/day?'+query,{cache:'no-store'});const data=await response.json();
  if(response.status===409&&data.code==='SOURCE_CHANGED'){rows.replaceChildren();cursor=null;revision=null;next.hidden=true;throw Error('카드 자료가 변경됐습니다. 지정 날짜로 다시 조회해 주세요.')}
  if(!response.ok)throw Error('카드 원행을 불러오지 못했습니다. 날짜와 접근 권한을 확인해 주세요.');
  if(data.filter_semantics!=='USER_DATE_FILTER'||data.date!==requestedDay)throw Error('지정한 날짜의 응답을 확인할 수 없습니다. 다시 조회해 주세요.');
  for(const tx of data.items||[])render(tx);
  cursor=data.cursor;revision=data.revision;next.hidden=!(data.has_more&&cursor);
  note.textContent=(confirmedDay&&requestedDay===confirmedDay?(basis==='FIRST_RECEIVED'?'최초 메일 수신일 기준 ':'예약 시각의 한국 날짜 '):'직접 지정한 날짜 ')+requestedDay+' · '+rows.children.length+' / '+data.total_count+'건. 결제 연결을 확정하지 않습니다.';
 }catch(error){note.textContent=error.message}finally{search.disabled=false;next.disabled=false}
}
filter.addEventListener('submit',event=>{event.preventDefault();if(dateInput.value&&filter.reportValidity())load(true)});
next.addEventListener('click',()=>load(false));
if(confirmedDay){dateInput.value=confirmedDay;details.open=true;load(true)}
}
function showBooking(b){
const card=document.createElement('article');card.className='fb-ticket';
const hero=document.createElement('header');hero.className='fb-hero';
text(hero,'span',b.cancelled?'취소·변경 근거 확인 필요':b.conflict?'원본 충돌 · 확인 필요':'예약 근거 확인','fb-status');
text(hero,'p','항공권 예약','fb-eyebrow');
text(hero,'h3',(b.booking_ref||'예약번호 미확인')+' · '+(b.passenger_name||'이름 미확인'));
text(hero,'p','예약된 항공권 정보를 한눈에 확인하세요.','fb-hero-subtitle');
const heroPlane=text(hero,'span','✈','fb-hero-plane');heroPlane.setAttribute('aria-hidden','true');
card.append(hero);
const summary=document.createElement('section');summary.className='fb-summary';
function summaryItem(label,value,symbol,extra){
 const wrap=document.createElement('div');wrap.className='fb-summary-item';
 const icon=text(wrap,'span',symbol,'fb-icon');icon.setAttribute('aria-hidden','true');
 const content=document.createElement('div');content.className='fb-summary-copy';
 text(content,'small',label);text(content,'strong',value||'확인되지 않음');
 if(extra)text(content,'span',extra,'fb-summary-detail');
 wrap.append(content);summary.append(wrap);
}
summaryItem('항공권 예약번호',b.booking_ref,'▣');
summaryItem('탑승객',b.passenger_name,'♙');
summaryItem('예약일',b.booking_date_status==='CONFLICT'?'근거 날짜 충돌':b.reserved_on||'확인되지 않음','▦',
 b.booking_date_status==='FIRST_RECEIVED'?'최초 메일 수신일 기준':b.booking_date_status==='EXPLICIT_LABEL'?'원본 명시 확인':null);
const dateTimes=(b.booking_date_evidence||[]).map(f=>f.timestamp).filter(Boolean);
summaryItem(b.booking_date_status==='FIRST_RECEIVED'?'최초 메일 수신 시각·시간대':'예약 근거 시각·시간대',
 dateTimes.length?[...new Set(dateTimes)].join(' / '):'확인되지 않음','✉');
summaryItem('원본 근거',b.source_verified?'최신 항공권 자료':'근거 확인 필요','▤');
card.append(summary);
const segments=document.createElement('section');segments.className='fb-section fb-itinerary';
const heading=document.createElement('div');heading.className='fb-heading';
const headingIcon=text(heading,'span','✈','fb-heading-icon');headingIcon.setAttribute('aria-hidden','true');
const headingCopy=document.createElement('div');text(headingCopy,'h2','탑승권·여정 정보');
text(headingCopy,'p','예약된 여정의 출발 및 도착 정보를 확인하세요.','fb-muted');
heading.append(headingCopy);segments.append(heading);
let legCount=0;
for(const [legIndex,leg] of (Array.isArray(b.legs)?b.legs:[]).entries()){
 const flights=Array.isArray(leg?.segments)&&leg.segments.length?leg.segments:[null];
 for(const [segmentIndex,flight] of flights.entries()){
  const trip=document.createElement('article');trip.className='fb-flight-card';
  const isReturn=/오는|return|inbound/i.test(String(leg?.label||'')) || legIndex>0;
  if(isReturn)trip.classList.add('fb-return');
  const bar=document.createElement('header');bar.className='fb-flight-bar';
  const badge=text(bar,'span',isReturn?'↘':'↗','fb-flight-badge');badge.setAttribute('aria-hidden','true');
  text(bar,'strong',String(leg?.label|| (isReturn?'오는편':'가는편'))+(flights.length>1?' · '+(segmentIndex+1)+'구간':''),'fb-flight-title');
  if(leg?.departure_on)text(bar,'span',leg.departure_on,'fb-flight-date');
  if(flight?.flight_number)text(bar,'span',flight.flight_number,'fb-flight-number');
  trip.append(bar);
  const route=document.createElement('div');route.className='fb-route';
  const from=document.createElement('div');from.className='fb-route-stop';
  text(from,'small','출발');text(from,'strong',leg?.origin_city||flight?.departure_airport||'확인되지 않음');
  if(flight?.departure_airport)text(from,'span',flight.departure_airport,'fb-airport-code');
  const arrow=text(route,'span','✈','fb-route-arrow');arrow.setAttribute('aria-hidden','true');
  const to=document.createElement('div');to.className='fb-route-stop';
  text(to,'small','도착');text(to,'strong',leg?.destination_city||flight?.arrival_airport||'확인되지 않음');
  if(flight?.arrival_airport)text(to,'span',flight.arrival_airport,'fb-airport-code');
  route.insertBefore(from,arrow);route.append(to);trip.append(route);
  const facts=document.createElement('div');facts.className='fb-flight-facts';
  if(leg?.departure_on)field(facts,'출발일',leg.departure_on);
  if(flight?.departure_time)field(facts,'출발 시간',flight.departure_time);
  if(flight?.arrival_time)field(facts,'도착 시간',flight.arrival_time);
  if(flight?.departure_airport||flight?.arrival_airport)field(facts,'출발 / 도착 공항',(flight.departure_airport||'?')+' → '+(flight.arrival_airport||'?'));
  if(facts.children.length)trip.append(facts);
  segments.append(trip);legCount++;
 }
}
if(!legCount)text(segments,'p','확인된 상세 여정 정보가 없습니다.','fb-muted');
card.append(segments);
const linked=document.createElement('div');linked.className='fb-section';text(linked,'h2','연결된 카드 결제');
if(Array.isArray(b.linked_cards)&&b.linked_cards.length){
text(linked,'p','사용자가 확인한 거래 연결입니다. 예약 전체의 결제 완료를 뜻하지 않습니다.','fb-note');
for(const tx of b.linked_cards){const info=document.createElement('div');info.className='fb-grid';
field(info,'거래일',tx.approval_date);field(info,'가맹점',tx.merchant);
field(info,'원화 금액',tx.amount_krw==null?null:String(tx.amount_krw)+'원');
field(info,'외화 금액·통화',[tx.foreign_amount,tx.currency].filter(v=>v!=null&&v!=='').join(' '));
field(info,'승인번호',tx.approval_number);field(info,'거래 유형',tx.event_type==='refund'?'환불 거래':'원결제 거래');
field(info,'취소 상태',tx.cancellation_status);field(info,'환불 상태',tx.refund_status);
field(info,'연결 근거','사용자 확인');linked.append(info);
if(tx.amount_status!=='MATCH'||tx.currency_status!=='MATCH')text(linked,'p','결제 근거와 카드 원행의 금액·통화 차이 또는 미확인 항목이 있습니다. 원본을 대조해 주세요.','fb-note');
if(typeof tx.detail_href==='string'&&tx.detail_href.startsWith('/board?row=')){const detail=text(linked,'a','카드 원행 상세 보기');detail.href=tx.detail_href}
}}else{text(linked,'p','이 조회에서는 확정된 카드 연결 근거를 아직 검증할 수 없습니다. 카드 거래가 없거나 미결제라는 뜻은 아닙니다.','fb-note')}
card.append(linked);
const candidateDay=['EXPLICIT_LABEL','FIRST_RECEIVED'].includes(b.booking_date_status)&&b.source_verified&&!b.conflict&&!b.cancelled&&!(b.linked_cards||[]).length?b.booking_card_day:null;
const candidates=document.createElement('div');candidates.className='fb-section';text(candidates,'h2','예약일의 카드 거래 후보');text(candidates,'p',candidateDay?(b.booking_date_status==='FIRST_RECEIVED'?'최초 메일 수신일을 예약일 기준으로 카드 거래 전체를 조회합니다. 날짜가 같아도 연결은 미확정입니다.':'원본 예약 시각의 한국 날짜로 카드 거래 전체를 후보로 조회합니다. 날짜가 같아도 연결이 확정된 것은 아닙니다.'):b.booking_date_status==='CONFLICT'?'예약일 원본끼리 날짜가 충돌해 자동 후보 조회를 보류합니다. 직접 날짜 조회만 가능합니다.':b.reserved_on?'자동 조회 조건을 충족하지 않아 직접 날짜 조회를 제공합니다.':'원본 예약일과 같은 예약번호의 최초 메일 수신일을 확인할 수 없어 자동 조회를 보류합니다. 날짜를 직접 선택해 주세요.','fb-muted');card.append(candidates);
const manualDate=text(candidates,'a','카드 전체 내역에서 날짜별 원행 확인');manualDate.href='/cards/all';
manualDateFilter(candidates,candidateDay,b.booking_date_status);
if(b.reserved_on&&!b.booking_card_day)text(candidates,'p','예약일 표기는 있지만 시간대 근거가 없어 자동 날짜 조회를 보류합니다. 날짜를 직접 선택해 주세요.','fb-muted');
const participant=document.createElement('details');participant.className='fb-section';
text(participant,'summary','참가자 연결 정보');
text(participant,'p','기존 참가자 연결 기능에서 예약 명단과 비교하고 COST 내부 연결을 확인할 수 있습니다.','fb-muted');
const link=text(participant,'a','참가자 연결 정보 열기');link.href='/flight-passengers?view=participants';card.append(participant);
return card}
let refreshAttempts=0,refreshTimer=null;
async function loadBookings(reset){
if(reset){resultRoot.replaceChildren();nextOffset=null;sourceRevision=null;more.hidden=true}
submit.disabled=true;more.disabled=true;status.textContent='항공권 예약 내역을 찾고 있습니다.';
try{
const response=await fetch('/api/flight-passengers/name-search',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF},body:JSON.stringify({name:searchName,offset:reset?0:nextOffset,revision:reset?null:sourceRevision}),cache:'no-store'});
const data=await response.json();if(!response.ok)throw new Error(({'INVALID_NAME':'탑승객 이름을 확인해 주세요.','CSRF_REQUIRED':'페이지를 새로고침한 뒤 다시 조회해 주세요.','FEATURE_DISABLED':'현재 이용할 수 없습니다.','STORE_UNAVAILABLE':'항공권 원본 자료를 불러올 수 없습니다.','SOURCE_CHANGED':'항공권 자료가 변경됐습니다. 이름을 다시 조회해 주세요.'})[data.code]||'항공권 조회에 실패했습니다.');
if(data.source_status==='LOADING'){
 status.textContent='항공권 메일 자료를 갱신하고 있습니다. 잠시 후 다시 조회합니다.';
 if(refreshAttempts++<60)refreshTimer=setTimeout(()=>loadBookings(true),2000);
 else status.textContent='항공권 메일 자료를 갱신하고 있습니다. 잠시 후 예약 조회를 눌러 주세요.';
 return;
}
for(const booking of data.reservations||[])resultRoot.append(showBooking(booking));
sourceRevision=data.revision;nextOffset=data.next_offset??null;more.hidden=nextOffset===null;
const count=resultRoot.querySelectorAll('.fb-ticket').length;
status.textContent=data.source_status==='UNAVAILABLE'?'최근 항공권 자료를 확인할 수 없습니다. 최신 수집 상태를 확인해 주세요.':count?'확인된 항공권 예약 '+(data.total??count)+'건 중 '+count+'건을 표시합니다. 같은 이름의 예약은 예약번호와 여정을 각각 확인해 주세요.':'이 이름으로 확인된 항공권 예약이 없습니다. 영문 표기를 확인해 주세요.';
}catch(error){status.textContent=error.message;more.hidden=true}finally{submit.disabled=false;more.disabled=false}}
form.addEventListener('submit',e=>{e.preventDefault();if(submit.disabled)return;clearTimeout(refreshTimer);refreshAttempts=0;searchName=form.elements.name.value.trim();loadBookings(true)});
more.addEventListener('click',()=>{if(nextOffset!==null&&!more.disabled)loadBookings(false)});
</script></body></html>""".replace('__CSRF__', token)

def _name_key(value):
    """Only normalize spelling and token order, never infer Korean transliteration."""
    from .flight_booking_projection import normalize_name_tokens
    return normalize_name_tokens(value)


def _confirmed_card_index(board, passenger_index):
    """Project only current owner-confirmed payment links from the held snapshot.

    No reconciliation, file reads, store creation, or inferred-link promotion here.
    The passenger and payment evidence must belong to the same fresh generation.
    """
    from app.ota_payments import _event_is_paid, _event_amount
    service = getattr(board, '_ota_snapshot_service', None)
    if service is None:
        return {}
    current, fresh = service.held()
    if not fresh or not current or not current.get('data'):
        return {}
    data = current['data']
    links = data.get('links') or {}
    events = {str(e.get('ota_event_id')): e for e in data.get('events') or []}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions') or []}
    owners = defaultdict(set)
    for event_id, link in links.items():
        if isinstance(link, dict) and link.get('transaction_id'):
            owners[str(link['transaction_id'])].add(str(event_id))
    for result in data.get('results') or []:
        event_id = str(result.get('ota_event_id') or '')
        ids = list(result.get('reserved_card_ids') or [])
        if result.get('status') in ('MATCHED_USER', 'MATCHED_AUTO') and result.get('transaction_id'):
            ids.append(result['transaction_id'])
        for transaction_id in ids:
            owners[str(transaction_id)].add(event_id)
    found = defaultdict(list)
    for result in data.get('results') or []:
        event_id = str(result.get('ota_event_id') or '')
        tid = str(result.get('transaction_id') or '')
        event, link, card = events.get(event_id), links.get(event_id), cards.get(tid)
        if (result.get('status') != 'MATCHED_USER' or not event or not isinstance(link, dict)
                or link.get('status') != 'MATCHED_USER' or not card
                or any(card.get(field) for field in ('duplicate_of', 'parse_error', 'conflict_reason'))
                or str(link.get('transaction_id') or '') != tid or owners[tid] != {event_id}):
            continue
        booking_ref = str(event.get('booking_ref') or '')
        evidence = passenger_index.get(booking_ref) or {}
        held_evidence = (data.get('passengers') or {}).get(booking_ref) or {}
        if (event.get('provider') != 'trip' or not evidence.get('digest')
                or evidence.get('conflict') or held_evidence.get('conflict')
                or held_evidence.get('digest') != evidence['digest']
                or not _event_is_paid(event) or _event_amount(event) is None
                or not link.get('source_digest')
                or link['source_digest'] != event.get('source_digest')
                or any(row.get('evidence_changed') or row.get('evidence_missing')
                       for row in (event, link, result))):
            continue
        currency = str(card.get('foreign_currency') or card.get('currency') or '').upper()
        event_currency = str(event.get('currency') or '').upper()
        amount_status = 'UNVERIFIED'
        left = event.get('amount_krw', event.get('amount')) if event_currency == 'KRW' else event.get('amount')
        right = card.get('amount_krw') if event_currency == 'KRW' else card.get('foreign_amount')
        if event_currency == 'KRW' or event_currency and event_currency == currency:
            try:
                a, b = Decimal(str(left)), Decimal(str(right))
                if a.is_finite() and b.is_finite():
                    amount_status = 'MATCH' if abs(a) == abs(b) else 'MISMATCH'
            except (InvalidOperation, ValueError):
                pass
        row = {key: card.get(key) for key in ('transaction_id', 'approval_date', 'merchant',
               'amount_krw', 'foreign_amount', 'refund_status', 'cancellation_status')}
        row.update(currency=currency, approval_number=card.get('approval_number') or card.get('authorization_id'),
                   direction=card.get('transaction_direction') or card.get('direction'),
                   event_type=event.get('event_type'), ota_event_id=event_id, link_source='USER_CONFIRMED',
                   amount_status=amount_status,
                   currency_status='MATCH' if currency and currency == event_currency else 'UNVERIFIED',
                   detail_href='/board?' + urlencode({'row': 'card-' + tid}))
        found[booking_ref].append(row)
    return found


def _name_search(board, name, *, offset=0, revision=None):
    """Search verified original-name tokens without requiring tour ID or full name."""
    query = _name_key(name)
    if not query:
        raise ValueError('INVALID_NAME')
    if type(offset) is not int or offset < 0 or offset > 1000000 or offset and not revision:
        raise ValueError('INVALID_CURSOR')
    from .flight_booking_index import passenger_index_for, source_status
    from .flight_booking_projection import query_booking_reservations
    index = passenger_index_for(board)
    cards = _confirmed_card_index(board, index)
    return query_booking_reservations(
        index,
        query_tokens=query,
        cards=cards,
        offset=offset,
        revision=revision,
        fallback_status_fn=lambda: source_status(board),
        name_key_fn=_name_key,
    )


def _passenger_evidence(board, booking_ref):
    from .ota_payment_review import passenger_index_for
    index = passenger_index_for(board, require_fresh=True)
    evidence = index.get(booking_ref)
    if not isinstance(evidence, dict) or not evidence.get('source_digests'):
        return None
    return evidence


def _candidate_result(board, booking_ref, tour_id, *, candidate_fetch=None):
    evidence = _passenger_evidence(board, booking_ref)
    if evidence is None:
        raise LookupError('VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND')
    if candidate_fetch is not None:
        snapshot = candidate_fetch(tour_id)
    else:
        from .guide_airfare_review import _token_file
        token_file = _token_file(board) if hasattr(board, 'path') else None
        snapshot = reservation_authority.fetch_passenger_candidates(
            tour_id, token=reservation_authority.configured_token(token_file))
    result = flight_passenger_matching.match_booking_passengers(evidence, snapshot)
    evidence_digest = result.get('evidence_digest')
    result['assignments'] = _assignments_for(booking_ref, tour_id, result['source_revision'], evidence_digest)
    # Link assignments by proposal_id for accurate matching
    by_proposal = {item.get('proposal_id'): item for item in result['assignments']}
    for passenger in result['passengers']:
        assignment = by_proposal.get(passenger.get('proposal_id'))
        if assignment:
            assignment = dict(assignment)
            assignment['candidate'] = next((candidate for candidate in passenger['candidates']
                                            if candidate.get('reference_id') == assignment.get('candidate_reference_id')), None)
        passenger['assignment'] = assignment
        passenger['cancellation_status'] = evidence.get('cancellation_status', 'NONE')
        passenger['evidence_conflict'] = bool(evidence.get('conflict'))
    result['stale_assignments'] = [item for item in result['assignments'] if item.get('stale')]
    return result


def _assignments_for(booking_ref, tour_id, source_revision, evidence_digest=None):
    """Read COST confirmations and mark them stale when reservation evidence changes."""
    path = _db_path()
    if path is None or not path.is_file():
        return []
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='flight_passenger_assignments'").fetchone()
        if not table:
            return []
        rows = conn.execute(
            'SELECT assignment_json FROM flight_passenger_assignments '
            'WHERE booking_ref=? AND tour_id=? ORDER BY created_at,rowid',
            (booking_ref, tour_id)).fetchall()
    finally:
        conn.close()
    values = []
    for (encoded,) in rows:
        try:
            assignment = json.loads(encoded)
        except (TypeError, json.JSONDecodeError):
            continue
        stale = (str(assignment.get('source_revision') or '') != str(source_revision or '')
                 or not assignment.get('candidate_reference_id') or not assignment.get('evidence_digest'))
        # Also mark stale if evidence_digest changed
        if str(assignment.get('evidence_digest') or '') != str(evidence_digest or ''):
            stale = True
        assignment['stale'] = stale
        values.append(assignment)
    return values


def _save_assignment(path, assignment):
    if path is None:
        raise ValueError('FLIGHT_PASSENGER_STORE_NOT_CONFIGURED')
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS flight_passenger_assignments(
            assignment_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE,
            booking_ref TEXT NOT NULL, tour_id TEXT NOT NULL, source_revision TEXT NOT NULL,
            assignment_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        current = conn.execute(
            'SELECT assignment_id,assignment_json FROM flight_passenger_assignments WHERE proposal_id=?',
            (assignment['proposal_id'],)).fetchone()
        encoded = json.dumps(assignment, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if current:
            if current[0] != assignment['assignment_id'] or current[1] != encoded:
                raise ValueError('PASSENGER_ASSIGNMENT_ALREADY_CONFIRMED')
            conn.commit()
            return assignment
        conn.execute('''INSERT INTO flight_passenger_assignments
            (assignment_id,proposal_id,booking_ref,tour_id,source_revision,assignment_json)
            VALUES(?,?,?,?,?,?)''',
            (assignment['assignment_id'], assignment['proposal_id'], assignment['booking_ref'],
             assignment['tour_id'], assignment['source_revision'], encoded))
        conn.commit()
        return assignment
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dispatch(handler, parsed, *, is_owner, board, raw=None, csrf='', query=None,
             candidate_fetch=None):
    if not owns_route(parsed.path):
        return False
    if not enabled():
        _send(handler, {'code': 'FEATURE_DISABLED'}, 404)
        return True
    if not is_owner:
        _send(handler, {'code': 'ACTION_FORBIDDEN'}, 403)
        return True
    if board is None:
        _send(handler, {'code': 'STORE_UNAVAILABLE'}, 503)
        return True
    query = query or parse_qs(getattr(parsed, 'query', '') or '')
    if parsed.path == ROUTES[0] and raw is None:
        from .flight_booking_index import prewarm
        prewarm(board)
        handler._send(_legacy_page(csrf) if query.get('view') == ['participants'] else _page(csrf))
        return True
    if parsed.path == ROUTES[1] and raw is None:
        booking_ref = str((query.get('booking_ref') or [''])[0]).strip()
        tour_id = str((query.get('tour_id') or query.get('tourFldid') or [''])[0]).strip()
        if not booking_ref or not tour_id:
            _send(handler, {'code': 'INVALID_VALUE'}, 422)
            return True
        try:
            result = _candidate_result(board, booking_ref, tour_id, candidate_fetch=candidate_fetch)
        except LookupError:
            _send(handler, {'code': 'VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND'}, 404)
        except reservation_authority.AuthorityUnavailable as exc:
            _send(handler, {'code': 'RESERVATION_AUTHORITY_' + exc.code.upper()}, 503)
        except (TypeError, ValueError):
            _send(handler, {'code': 'PASSENGER_AUTHORITY_INVALID'}, 503)
        else:
            _send(handler, result)
        return True
    if parsed.path == ROUTES[3]:
        if raw is None:
            _send(handler, {'code': 'METHOD_NOT_ALLOWED'}, 405)
            return True
        if not csrf or handler.headers.get('X-CSRF-Token') != csrf:
            _send(handler, {'code': 'CSRF_REQUIRED'}, 403)
            return True
        try:
            payload = json.loads(raw.decode('utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('INVALID_NAME')
            name = payload.get('name')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
                raise ValueError('INVALID_NAME')
            result = _name_search(board, name.strip(), offset=payload.get('offset', 0),
                                  revision=payload.get('revision'))
        except LookupError:
            _send(handler, {'code': 'SOURCE_CHANGED'}, 409)
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            _send(handler, {'code': 'INVALID_NAME'}, 422)
        else:
            _send(handler, result)
        return True
    if parsed.path != ROUTES[2] or raw is None:
        _send(handler, {'code': 'METHOD_NOT_ALLOWED'}, 405)
        return True
    if not csrf or handler.headers.get('X-CSRF-Token') != csrf:
        _send(handler, {'code': 'CSRF_REQUIRED'}, 403)
        return True
    try:
        payload = json.loads(raw.decode('utf-8'))
        booking_ref = str(payload.get('booking_ref') or '').strip()
        tour_id = str(payload.get('tour_id') or '').strip()
        proposal_id = str(payload.get('proposal_id') or '').strip()
        candidate_reference_id = str(payload.get('candidate_reference_id') or '').strip()
        result = _candidate_result(board, booking_ref, tour_id, candidate_fetch=candidate_fetch)
        proposal = next((item for item in result['passengers']
                         if item['proposal_id'] == proposal_id), None)
        if proposal is None:
            raise ValueError('PASSENGER_CANDIDATE_REQUIRED')
        if proposal.get('cancellation_status') != 'NONE':
            raise ValueError('PASSENGER_CANDIDATE_REQUIRED')
        assignment = flight_passenger_matching.build_user_assignment(
            proposal, candidate_reference_id=candidate_reference_id, actor='owner',
            current_source_revision=result['source_revision'],
            current_evidence_digest=result.get('evidence_digest'))
        saved = _save_assignment(_db_path(), assignment)
    except LookupError:
        _send(handler, {'code': 'VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND'}, 404)
    except reservation_authority.AuthorityUnavailable as exc:
        _send(handler, {'code': 'RESERVATION_AUTHORITY_' + exc.code.upper()}, 503)
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        code = str(exc) if str(exc).startswith('PASSENGER_') or str(exc).startswith('FLIGHT_') else 'INVALID_VALUE'
        _send(handler, {'code': code}, 409 if code != 'INVALID_VALUE' else 422)
    else:
        _send(handler, {'code': 'OK', 'assignment': saved})
    return True
