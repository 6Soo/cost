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
<h1>항공권 참가자 연결</h1>
<form id='search' aria-label='항공권 참가자 연결 검색'><label for='f-booking'>항공권 예약번호<input id='f-booking' name='booking_ref' required autocomplete='off'></label><label for='f-tour'>예약 시스템 여행 ID<input id='f-tour' name='tour_id' required autocomplete='off'></label><button id='search-submit' type='submit'>연결 후보 찾기</button></form>
<p id='status' role='status' aria-live='polite'></p><section id='results' aria-label='후보 결과'></section>
</main><script>
const csrf=""" + token + """;
const form=document.querySelector('#search'), status=document.querySelector('#status'), root=document.querySelector('#results'), searchButton=document.querySelector('#search-submit');
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
if(!passenger.candidates.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='연결할 참가자 후보가 없습니다. 예약 명단과 영문 이름을 확인해 주세요.';const source=document.createElement('a');source.href='/reserve-links';source.textContent='예약 명단·여행 연결 확인';article.append(empty,source)}
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
:root{--bg:#f8fafc;--paper:#fff;--ink:#0f172a;--mut:#475569;--line:#e2e8f0;--hover:#f1f5f9;--focus:#2563eb;--warn:#a16207}
@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--paper:#1e293b;--ink:#f8fafc;--mut:#cbd5e1;--line:#334155;--hover:#334155;--focus:#93c5fd;--warn:#fbbf24}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:0.9375rem/1.5 system-ui,"Malgun Gothic",sans-serif}
#flight-booking-page{max-width:880px;margin:24px auto;padding:0 20px 48px}
#flight-booking-page h1{font-size:1.5rem;line-height:1.3;margin:0 0 12px}
#flight-booking-page h2,#flight-booking-page h3{font-size:1rem;line-height:1.4;margin:0 0 8px;overflow-wrap:anywhere}
#flight-booking-page p{margin:0 0 12px;overflow-wrap:anywhere}.fb-muted{color:var(--mut)}
.fb-panel,.fb-ticket,.fb-booking-choice{background:var(--paper);border:1px solid var(--line);border-radius:10px}
.fb-panel{padding:14px}.fb-ticket,.fb-booking-choice{margin:12px 0;min-width:0}
.fb-booking-choice .fb-ticket{margin:0;border:0;border-radius:0}.fb-booking-choice .fb-hero{display:none}
#flight-booking-page form{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}
#flight-booking-page label{display:grid;gap:6px;flex:1 1 180px;min-width:0;font-size:0.875rem;font-weight:600}
#flight-booking-page input,#flight-booking-page button{font:inherit;min-height:44px;padding:9px 12px;border:1px solid var(--mut);border-radius:7px;background:var(--paper);color:var(--ink)}
#flight-booking-page input{width:100%;min-width:0;font-size:1rem}
#flight-booking-page button{cursor:pointer;font-weight:600;overflow-wrap:anywhere}
#flight-booking-page button:disabled{opacity:.6;cursor:wait}
#flight-booking-page #fb-submit{background:var(--ink);color:var(--paper);border-color:var(--ink)}
#flight-booking-page :is(button,input,summary,a):focus-visible{outline:2px solid var(--focus);outline-offset:3px}
#flight-booking-page #fb-search{flex-wrap:nowrap}#flight-booking-page #fb-submit{flex-shrink:0;white-space:nowrap}
#flight-booking-page #fb-search-help{display:block;margin-top:8px;font-size:0.8125rem;color:var(--mut)}
#fb-status{margin:8px 0 0!important;font-size:0.875rem}#fb-status:empty{display:none}#fb-results{margin-top:12px}
#flight-booking-page summary{display:flex;align-items:center;gap:12px;min-height:44px;padding:10px 0;list-style:none;font-weight:600;cursor:pointer;line-height:1.5;overflow-wrap:anywhere}
#flight-booking-page summary::-webkit-details-marker{display:none}
#flight-booking-page summary::after{content:'';flex:0 0 7px;width:7px;height:7px;margin-inline-start:auto;margin-inline-end:4px;border-inline-end:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg)}
#flight-booking-page details[open]>summary::after{transform:rotate(225deg)}
#flight-booking-page .fb-booking-choice>summary{padding:14px 16px}
.fb-choice-copy{min-width:0}.fb-choice-copy strong,.fb-choice-copy small{display:block;overflow-wrap:anywhere}
.fb-choice-copy strong{font-size:1rem}.fb-choice-copy small{font-size:0.8125rem;color:var(--mut);font-weight:400;margin-top:3px}
.fb-trip-group{margin:24px 0}.fb-group-heading{display:flex;align-items:baseline;gap:8px 12px;flex-wrap:wrap;padding-bottom:4px}.fb-group-heading h2{margin:0!important}.fb-group-count{font-size:0.8125rem;color:var(--mut)}.fb-group-heading a{color:var(--ink);font-size:0.8125rem;min-height:44px;display:inline-flex;align-items:center;margin-inline-start:auto;text-underline-offset:3px}.fb-group-unavailable{font-size:0.875rem;color:var(--mut)}
.fb-hero{padding:16px}.fb-hero h3{font-size:1.125rem!important;margin:0!important}.fb-hero-subtitle{color:var(--mut);font-size:0.875rem;margin:4px 0 0!important}
.fb-section{padding:14px 16px;border-top:1px solid var(--line)}.fb-heading{margin-bottom:4px}
.fb-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:12px 16px}
.fb-summary-item,.fb-field{min-width:0}.fb-summary small,.fb-field small{display:block;color:var(--mut);font-size:0.8125rem;font-weight:400;margin-bottom:3px}
.fb-summary strong,.fb-field strong{display:block;overflow-wrap:anywhere;font-size:0.9375rem}.fb-summary-detail{font-size:0.8125rem;color:var(--mut);display:block;margin-top:2px}
.fb-reservation-warning{margin:0 16px 12px;padding:12px;border-inline-start:3px solid var(--warn);background:var(--hover)}
.fb-reservation-warning h3{font-size:0.9375rem!important}.fb-reservation-warning p{font-size:0.875rem}
.fb-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
#flight-booking-page .fb-actions a{display:inline-flex;align-items:center;min-height:44px;padding:8px 10px;text-decoration:underline;text-underline-offset:3px;color:var(--ink);font-weight:600}
#flight-booking-page .fb-actions button{font-size:0.875rem}.fb-copy-status{font-size:0.8125rem;margin:8px 0 0!important;min-height:0}
.fb-note{padding:9px 12px;border-inline-start:3px solid var(--warn);background:var(--hover);font-size:0.875rem}
.fb-flight-card{padding:10px 0;min-width:0}.fb-flight-card+.fb-flight-card{border-top:1px solid var(--line)}
.fb-flight-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:0.8125rem}.fb-flight-title,.fb-flight-date{color:var(--mut);font-weight:400}
.fb-flight-number{margin-inline-start:auto;font-weight:600;overflow-wrap:anywhere;max-width:100%}
.fb-route{display:grid;grid-template-columns:minmax(0,1fr) 20px minmax(0,1fr);gap:8px;align-items:center;padding-top:6px}
.fb-route-stop{min-width:0}.fb-route-stop:last-child{text-align:end}.fb-route-stop strong{display:block;font-size:0.875rem;overflow-wrap:anywhere}
.fb-time{display:block;font-size:1.25rem;line-height:1.3;font-variant-numeric:tabular-nums}.fb-airport-code{font-size:0.8125rem;color:var(--mut)}.fb-route-arrow{color:var(--mut);text-align:center}
.fb-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.fb-payment-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;flex-wrap:wrap}
.fb-amount{font-size:1.125rem;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.fb-date-row{border:1px solid var(--line);padding:12px;border-radius:7px;margin:12px 0}.fb-date-row .fb-grid{margin-top:10px}
.fb-date-filter{margin-top:8px}.fb-date-filter form{margin:8px 0}.fb-date-filter>.fb-note{font-size:0.8125rem;background:none;border:0;padding:0;color:var(--mut)}
.fb-date-status{font-size:0.875rem;margin:8px 0!important}.fb-date-filter button{flex-shrink:0}.fb-more-details{font-size:0.875rem}.fb-more-details>summary{color:var(--mut)}
.fb-card-detail dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 12px}.fb-card-detail dd{margin:0;overflow-wrap:anywhere}.fb-card-detail dt{color:var(--mut)}
.fb-passengers{padding:0 16px 12px;overflow-wrap:anywhere;font-size:0.875rem}.fb-passengers p{margin:0!important}.fb-passengers small{color:var(--mut)}
#flight-booking-page [hidden]{display:none!important}
@media(max-width:600px){#flight-booking-page{margin:12px auto;padding:0 12px 32px}#flight-booking-page h1{font-size:1.25rem}.fb-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.fb-summary-item:first-child{grid-column:1/-1}.fb-grid{grid-template-columns:minmax(0,1fr)}#flight-booking-page .fb-booking-choice>summary{padding:12px}.fb-section{padding:12px}.fb-summary,.fb-hero{padding:12px}.fb-reservation-warning{margin-inline:12px}.fb-date-filter form{display:grid;grid-template-columns:minmax(0,1fr)}.fb-date-filter label{width:100%}.fb-date-filter form button{justify-self:start}}
</style></head><body><main id="flight-booking-page">
<h1>항공권 예약 확인</h1>
<section class="fb-panel fb-search-panel" aria-label="항공권 조회">
<form id="fb-search"><label for="fb-name">항공권 검색<input id="fb-name" name="name" placeholder="예: 22일 시즈오카, fuk, 탑승객 이름" aria-describedby="fb-search-help" autocomplete="off" required maxlength="100"></label><button type="submit" id="fb-submit">예약 조회</button></form>
<span id="fb-search-help">이름·행선지·공항 코드·여행 중 날짜로 검색</span>
<p class="fb-muted" id="fb-status" role="status" aria-live="polite"></p></section>
<section id="fb-results" aria-label="예약 조회 결과"></section><button id="fb-more" type="button" hidden>예약 더 보기</button></main>
<script>
const CSRF=__CSRF__;
const form=document.getElementById('fb-search'),resultRoot=document.getElementById('fb-results'),status=document.getElementById('fb-status'),submit=document.getElementById('fb-submit');
const more=document.getElementById('fb-more');let nextOffset=null,sourceRevision=null,searchName='';
function text(parent,tag,value,klass){const e=document.createElement(tag);if(klass)e.className=klass;e.textContent=String(value??'');parent.append(e);return e}
function field(parent,label,value){const wrap=document.createElement('div');wrap.className='fb-field';text(wrap,'small',label);text(wrap,'strong',value||'확인되지 않음');parent.append(wrap)}
function money(value,currency='KRW'){
 if(value==null||value==='')return '';
 const n=Number(value);if(!Number.isFinite(n))return '금액 확인 필요';
 return new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2}).format(n)+(currency==='KRW'?'원':' '+currency);
}
function cardTransaction(parent,tx,candidate=false){
 const row=document.createElement('article');row.className='fb-date-row';
 const head=text(row,'div','','fb-payment-head');text(head,'h3',tx.merchant||'가맹점 미확인');
 const currency=tx.foreign_currency||tx.currency;
 text(head,'strong',money(tx.amount_krw)||money(tx.foreign_amount,currency)||'금액 확인 필요','fb-amount');
 const grid=text(row,'div','','fb-grid');field(grid,'거래일',tx.approval_date);
 const direction=tx.transaction_direction||tx.direction||tx.event_type;
 field(grid,'거래 유형',({purchase:'결제',charge:'결제',refund:'취소·환불',cancel:'취소',cancellation:'취소'})[direction]||'유형 확인 필요');
 if(tx.card_tail||tx.issuer)field(grid,'결제 카드',[tx.issuer,tx.card_tail?'끝 '+tx.card_tail:''].filter(Boolean).join(' · '));
 if(tx.foreign_amount!=null&&currency)field(grid,'외화 금액',money(tx.foreign_amount,currency));
 const protections=[];if(tx.duplicate_of)protections.push('중복 원행');if(tx.conflict_reason)protections.push('원본 충돌');if(tx.parse_error)protections.push('원본 오류');
 if(protections.length)text(row,'p',protections.join(' · '),'fb-note');
 if(!candidate&&(tx.amount_status!=='MATCH'||tx.currency_status!=='MATCH'))text(row,'p','결제 근거와 카드 원행의 금액·통화 차이 또는 미확인 항목이 있습니다. 원본을 대조해 주세요.','fb-note');
 if(tx.approval_number){const detail=text(row,'details','','fb-payment-detail');text(detail,'summary','승인 정보');field(detail,'승인번호',tx.approval_number)}
 if(tx.transaction_id){const detail=text(row,'details','','fb-card-detail');text(detail,'summary','카드 원행 상세');const content=text(detail,'div','');
 detail.addEventListener('toggle',async()=>{if(!detail.open||detail.dataset.loaded||detail.dataset.loading)return;detail.dataset.loading='1';content.textContent='원행을 불러오는 중입니다.';
 try{const response=await fetch('/api/cards/transactions/detail?'+new URLSearchParams({id:tx.transaction_id}),{cache:'no-store'});if(!response.ok)throw Error(response.status===401||response.status===403?'로그인과 조회 권한을 확인해 주세요.':'원행을 불러오지 못했습니다. 닫았다 다시 열어 주세요.');const data=await response.json();if(typeof data.html!=='string')throw Error('원행을 확인할 수 없습니다.');const parsed=new DOMParser().parseFromString(data.html,'text/html');const facts=parsed.querySelector('dl.card-detail-fields');content.replaceChildren();if(facts)content.append(facts);else content.textContent='표시할 원행 상세가 없습니다.';detail.dataset.loaded='1'}catch(error){content.textContent=error.message}finally{delete detail.dataset.loading}})}
 parent.append(row);
}
function manualDateFilter(parent,confirmedDay=null,basis='EXPLICIT_LABEL'){
const details=document.createElement('details');details.className='fb-date-filter';parent.append(details);
text(details,'summary','날짜로 카드 내역 조회');
text(details,'p',confirmedDay?(basis==='FIRST_RECEIVED'?'별도 예약일이 없어 보관된 인증 메일의 최초 수신일을 예약일 기준으로 사용합니다. 결제 연결은 미확정입니다.':'원본 예약 시각과 시간대를 한국 시간으로 환산한 날짜입니다. 결제 연결이 확정된 것은 아닙니다.'):'카드 이용 날짜를 선택해 조회하세요. 조회만으로 예약과 카드 결제가 연결되지는 않습니다.','fb-note');
const filter=document.createElement('form'),label=text(filter,'label','조회 날짜');
const dateInput=document.createElement('input');dateInput.type='date';dateInput.required=true;dateInput.min='2000-01-01';dateInput.max='2100-12-31';label.append(dateInput);
const search=text(filter,'button','카드 내역 조회');search.type='submit';details.append(filter);
const note=text(details,'p','조회할 날짜를 선택하세요.','fb-date-status');note.setAttribute('role','status');note.setAttribute('aria-live','polite');
const rows=document.createElement('div');details.append(rows);
const next=text(details,'button','카드 원행 더 보기');next.type='button';next.hidden=true;
let activeDay='',cursor=null,revision=null,version=0,controller=null;
const render=tx=>{
 cardTransaction(rows,tx,true);
};
async function load(reset){
 if(reset){version++;if(controller)controller.abort();activeDay=dateInput.value;cursor=null;revision=null;rows.replaceChildren();next.hidden=true}
 const requestedDay=activeDay,requestVersion=version;controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);search.disabled=true;next.disabled=true;note.textContent='카드 원행을 읽고 있습니다.';
 try{
  const query=new URLSearchParams({date:requestedDay});if(cursor){query.set('cursor',cursor);query.set('revision',revision)}
  const response=await fetch('/api/cards/transactions/day?'+query,{cache:'no-store',signal:controller.signal});const data=await response.json();if(requestVersion!==version)return;
  if(response.status===409&&data.code==='SOURCE_CHANGED'){rows.replaceChildren();cursor=null;revision=null;next.hidden=true;throw Error('카드 자료가 변경됐습니다. 지정 날짜로 다시 조회해 주세요.')}
  if(!response.ok)throw Error('카드 원행을 불러오지 못했습니다. 날짜와 접근 권한을 확인해 주세요.');
  if(data.filter_semantics!=='USER_DATE_FILTER'||data.date!==requestedDay)throw Error('지정한 날짜의 응답을 확인할 수 없습니다. 다시 조회해 주세요.');
  for(const tx of data.items||[])render(tx);
  cursor=data.cursor;revision=data.revision;next.hidden=!(data.has_more&&cursor);
  note.textContent=(confirmedDay&&requestedDay===confirmedDay?(basis==='FIRST_RECEIVED'?'최초 인증 메일 수신일 기준 ':'예약 시각의 한국 날짜 '):'직접 지정한 날짜 ')+requestedDay+' · '+(data.total_count?rows.children.length+' / '+data.total_count+'건':'카드 내역이 없습니다. 다른 날짜를 선택해 다시 조회하세요')+'. 결제 연결을 확정하지 않습니다.';
 }catch(error){if(requestVersion===version)note.textContent=error.name==='AbortError'?'카드 조회 응답이 지연되고 있습니다. 카드 내역 조회를 눌러 다시 시도하세요.':error.message}finally{clearTimeout(timeout);if(requestVersion===version){search.disabled=false;next.disabled=false}}
}
filter.addEventListener('submit',event=>{event.preventDefault();if(dateInput.value&&filter.reportValidity())load(true)});
next.addEventListener('click',()=>load(false));
if(confirmedDay){dateInput.value=confirmedDay;const loadVisible=()=>{if(details.open&&details.checkVisibility()&&!activeDay)load(true)};details.addEventListener('toggle',loadVisible);details.addEventListener('fb-visible',loadVisible)}
}
function passengerNames(b){return Array.isArray(b.passengers)&&b.passengers.length?b.passengers:[b.passenger_name].filter(Boolean)}
function passengerTitle(b){const people=passengerNames(b);return people.slice(0,3).join(' · ')+(people.length>3?' 외 '+(people.length-3)+'명':'')||'탑승객 미확인'}
function providerInfo(b){return ({trip:{name:'Trip.com',url:'https://kr.trip.com/'},jeju:{name:'제주항공',url:'https://www.jejuair.net/'},asiana:{name:'아시아나항공',url:'https://flyasiana.com/'},skyticket:{name:'스카이티켓',url:'https://ko.skyticket.com/'}})[b.provider]||{name:b.provider||'예약처 미확인'}}
function reservationWarning(card,b){
 const conflict=b.conflict||b.cancellation_status==='CONFLICT',cancelled=b.cancelled;
 if(!conflict&&!cancelled&&b.source_verified&&b.booking_date_status!=='CONFLICT')return;
 const warning=text(card,'section','','fb-reservation-warning');
 text(warning,'h3',conflict?'예약 자료가 서로 일치하지 않습니다':cancelled?'취소·변경 자료가 포함된 예약입니다':b.booking_date_status==='CONFLICT'?'예약일 근거가 서로 다릅니다':'예약 원본을 검증하지 못했습니다');
 text(warning,'p',conflict||cancelled?'아래 일정은 저장된 자료입니다. 예약처에서 예약번호와 탑승객명으로 현재 일정·취소 여부를 대조하세요.':'예약처에서 예약번호와 탑승객명을 대조하세요. 카드 내역은 아래에서 날짜를 지정해 조회할 수 있습니다.');
 const provider=providerInfo(b),actions=text(warning,'div','','fb-actions');
 if(provider.url){const link=text(actions,'a',provider.name+'에서 예약 확인');link.href=provider.url;link.target='_blank';link.rel='noopener noreferrer';link.setAttribute('aria-label',provider.name+'에서 예약 확인 (새 탭)')}
 if(b.booking_ref){const copy=text(actions,'button','예약번호 복사');copy.type='button';const status=text(warning,'p','','fb-copy-status');status.setAttribute('role','status');copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(String(b.booking_ref));status.textContent='예약번호를 복사했습니다.'}catch{status.textContent='복사하지 못했습니다. 예약번호 '+b.booking_ref+'를 직접 선택해 복사하세요.'}})}
 if(!provider.url)text(warning,'p','예약처를 확인할 수 없습니다. 보관한 예약 확인서의 예약번호와 탑승객명을 대조하세요.','fb-muted');
}
function showBooking(b){
const card=document.createElement('article');card.className='fb-ticket';
const hero=document.createElement('header');hero.className='fb-hero';
text(hero,'h3',passengerTitle(b));
const routeLeg=(b.legs||[])[0];if(routeLeg)text(hero,'p',[routeLeg.origin_city,routeLeg.destination_city].filter(Boolean).join(' → '),'fb-hero-subtitle');
const legs=Array.isArray(b.legs)?b.legs:[];
card.append(hero);
const people=passengerNames(b);
if(people.length>3){const roster=text(card,'section','','fb-passengers');text(roster,'small','탑승객 '+people.length+'명');text(roster,'p',people.join(' · '));}
reservationWarning(card,b);
const summary=document.createElement('section');summary.className='fb-summary';
function summaryItem(label,value,extra){
 const wrap=document.createElement('div');wrap.className='fb-summary-item';
 const content=document.createElement('div');content.className='fb-summary-copy';
 text(content,'small',label);text(content,'strong',value||'확인되지 않음');
 if(extra)text(content,'span',extra,'fb-summary-detail');
 wrap.append(content);summary.append(wrap);
}
summaryItem('예약번호',b.booking_ref);
summaryItem('예약일',b.booking_date_status==='CONFLICT'?'근거 날짜 충돌':b.reserved_on||'확인되지 않음',
 b.booking_date_status==='FIRST_RECEIVED'?'최초 메일 수신일 기준':b.booking_date_status==='EXPLICIT_LABEL'?'원본 명시 확인':null);
summaryItem('예약처',providerInfo(b).name);
card.append(summary);
const segments=document.createElement('section');segments.className='fb-section fb-itinerary';
const heading=document.createElement('div');heading.className='fb-heading';
const headingCopy=document.createElement('div');text(headingCopy,'h3','탑승권·여정 정보');
heading.append(headingCopy);segments.append(heading);
let legCount=0;
for(const [legIndex,leg] of (Array.isArray(b.legs)?b.legs:[]).entries()){
 const flights=Array.isArray(leg?.segments)&&leg.segments.length?leg.segments:[null];
 for(const [segmentIndex,flight] of flights.entries()){
  const trip=document.createElement('article');trip.className='fb-flight-card';
  const isReturn=/오는|return|inbound/i.test(String(leg?.label||''));
  if(isReturn)trip.classList.add('fb-return');
  const bar=document.createElement('header');bar.className='fb-flight-bar';
  text(bar,'strong',String(leg?.label|| (isReturn?'오는편':legIndex===0?'가는편':'여정 '+(legIndex+1)))+(flights.length>1?' · '+(segmentIndex+1)+'구간':''),'fb-flight-title');
  if(leg?.departure_on)text(bar,'span',leg.departure_on,'fb-flight-date');
  if(flight?.flight_number)text(bar,'span',flight.flight_number,'fb-flight-number');
  trip.append(bar);
  const route=document.createElement('div');route.className='fb-route';
  const from=document.createElement('div');from.className='fb-route-stop';
  if(flight?.departure_time){const time=text(from,'b',flight.departure_time,'fb-time');time.setAttribute('aria-label','출발 시간 '+flight.departure_time)}
  text(from,'strong',flights.length>1?(flight?.departure_airport||'공항 미확인'):(leg?.origin_city||flight?.departure_airport||'확인되지 않음'));
  if(flight?.departure_airport&&from.querySelector('strong').textContent!==flight.departure_airport)text(from,'span',flight.departure_airport,'fb-airport-code');
  const arrow=text(route,'span','→','fb-route-arrow');arrow.setAttribute('aria-hidden','true');
  const to=document.createElement('div');to.className='fb-route-stop';
  if(flight?.arrival_time){const time=text(to,'b',flight.arrival_time,'fb-time');time.setAttribute('aria-label','도착 시간 '+flight.arrival_time)}
  text(to,'strong',flights.length>1?(flight?.arrival_airport||'공항 미확인'):(leg?.destination_city||flight?.arrival_airport||'확인되지 않음'));
  if(flight?.arrival_airport&&to.querySelector('strong').textContent!==flight.arrival_airport)text(to,'span',flight.arrival_airport,'fb-airport-code');
  route.insertBefore(from,arrow);route.append(to);trip.append(route);
  segments.append(trip);legCount++;
 }
}
if(!legCount)text(segments,'p','확인된 상세 여정 정보가 없습니다.','fb-muted');
card.append(segments);

const linked=document.createElement('div');linked.className='fb-section fb-payments';text(linked,'h3','카드 결제');
if(Array.isArray(b.linked_cards)&&b.linked_cards.length){
text(linked,'p','연결 확인 · 예약 전체의 결제 완료를 뜻하지 않습니다.','fb-muted');
for(const tx of b.linked_cards)cardTransaction(linked,tx);
}else{text(linked,'p','연결된 카드 결제가 없습니다. 미결제를 뜻하지는 않습니다.','fb-muted')}
card.append(linked);
const candidateDay=['EXPLICIT_LABEL','FIRST_RECEIVED'].includes(b.booking_date_status)&&b.source_verified&&!b.conflict&&!b.cancelled&&!(b.linked_cards||[]).length?b.booking_card_day:null;
const candidates=linked;
manualDateFilter(candidates,candidateDay,b.booking_date_status);
if(!(b.linked_cards||[]).length)candidates.querySelector('.fb-date-filter').open=true;
if(b.reserved_on&&!b.booking_card_day)text(candidates,'p','예약일 원문은 '+b.reserved_on+'입니다. 카드 이용 날짜와 다를 수 있어 자동 조회하지 않았습니다.','fb-muted');
const evidence=text(card,'details','','fb-section fb-more-details fb-evidence');text(evidence,'summary','예약일 근거');
text(evidence,'p',b.booking_date_status==='FIRST_RECEIVED'?'최초 메일 수신일 기준입니다. 실제 예약 생성일·발권일·결제일과 다를 수 있습니다.':b.booking_date_status==='EXPLICIT_LABEL'?'원본에 명시된 예약일입니다. 발권일·결제일과 구분합니다.':'예약일을 확정할 수 있는 원본 근거가 없습니다.','fb-muted');
const dateTimes=(b.booking_date_evidence||[]).map(f=>f.timestamp).filter(Boolean);
if(dateTimes.length)field(evidence,'근거 시각·시간대',[...new Set(dateTimes)].join(' / '));
text(evidence,'p','예약 확인 자료에서 조회한 정보입니다. 실제 탑승·현재 운항 여부는 항공사에서 확인하세요.','fb-muted');
return card}
let refreshAttempts=0,refreshTimer=null,refreshStarted=0;
const bookingGroups=new Map();
function groupForBooking(b){
 const unavailable=b.trip_assignment_available===false;
 const id=b.assigned_trip_tab_id||'',conflict=!id&&b.assignment_status==='CONFLICT';
 const key=id?'trip:'+id:unavailable?'unavailable':conflict?'conflict':'unassigned';
 if(!bookingGroups.has(key)){
  const section=text(resultRoot,'section','','fb-trip-group');section.dataset.tripId=id;
  const head=text(section,'header','','fb-group-heading');
  text(head,'h2',id?b.assigned_trip_title||id:unavailable?'여행 배정 확인 불가':conflict?'여행 배정 충돌':'여행 미배정');
  const count=text(head,'span','','fb-group-count');
  if(id){const link=text(head,'a','여행 장부');link.href='/board?'+new URLSearchParams({tab:id})}
  if(unavailable)text(section,'p','여행 배정 자료를 읽지 못했습니다. 예약 조회를 눌러 다시 시도하세요.','fb-group-unavailable');
  const list=text(section,'div','','fb-trip-bookings');
  bookingGroups.set(key,{section,list,count,order:id?'0'+(b.assigned_trip_starts_on||''):'1'+key});
 }
 const group=bookingGroups.get(key);
 return group;
}
function updateGroups(){
 const ordered=[...bookingGroups.values()].sort((a,b)=>{
  if(a.order[0]!==b.order[0])return a.order[0].localeCompare(b.order[0]);
  return b.order.localeCompare(a.order);
 });
 for(const group of ordered){group.count.textContent=group.list.querySelectorAll('.fb-ticket').length+'건 표시';resultRoot.append(group.section)}
}
async function loadBookings(reset,poll=false){
if(reset){resultRoot.replaceChildren();bookingGroups.clear();nextOffset=null;sourceRevision=null;more.hidden=true}
let waiting=false;
resultRoot.setAttribute('aria-busy','true');submit.disabled=true;more.disabled=true;
if(!poll)status.textContent='항공권 예약 내역을 찾고 있습니다.';
const controller=new AbortController(),requestTimer=setTimeout(()=>controller.abort(),15000);
try{
const response=await fetch('/api/flight-passengers/name-search',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF},body:JSON.stringify({name:searchName,offset:reset?0:nextOffset,revision:reset?null:sourceRevision}),cache:'no-store',signal:controller.signal});
if(response.status===401||response.redirected)throw Error('로그인이 필요합니다. 새로고침 후 로그인해 주세요.');
const data=await response.json();if(!response.ok){if(data.code==='SOURCE_CHANGED'){resultRoot.replaceChildren();bookingGroups.clear();nextOffset=null;sourceRevision=null;more.hidden=true}throw new Error(({'INVALID_NAME':'검색어와 날짜를 확인해 주세요.','CSRF_REQUIRED':'페이지를 새로고침한 뒤 다시 조회해 주세요.','FEATURE_DISABLED':'현재 이용할 수 없습니다.','STORE_UNAVAILABLE':'항공권 원본 자료를 불러오지 못했습니다. 잠시 후 예약 조회를 눌러 다시 시도하세요.','SOURCE_CHANGED':'항공권 자료가 변경됐습니다. 다시 조회해 주세요.'})[data.code]||'항공권 조회에 실패했습니다. 예약 조회 또는 더 보기를 눌러 다시 시도하세요.')}
if(data.source_status==='LOADING'){
 const notice='항공권 자료를 준비하고 있습니다. 완료되면 자동으로 조회합니다. 최대 2분 정도 기다려 주세요.';
 if(refreshAttempts++<60&&Date.now()-refreshStarted<120000){
  if(status.textContent!==notice)status.textContent=notice;
  waiting=true;refreshTimer=setTimeout(()=>loadBookings(true,true),2000);
 }else status.textContent='항공권 자료 준비가 지연되고 있습니다. 예약 조회를 눌러 다시 시도해 주세요.';
 return;
}
for(const booking of data.reservations||[]){const group=groupForBooking(booking),ticket=showBooking(booking);if((data.total??data.reservations.length)>1){
 const item=document.createElement('details');item.className='fb-booking-choice';
 const summary=text(item,'summary',''),copy=text(summary,'span','','fb-choice-copy');
 const legs=booking.legs||[],first=legs.find(leg=>leg.segments?.length)||legs[0];
 const route=first?[first.origin_city||first.segments?.[0]?.departure_airport,first.destination_city||first.segments?.at(-1)?.arrival_airport].filter(Boolean).join(' → '):'';
 const days=[...new Set(legs.map(leg=>leg.departure_on).filter(Boolean))].sort();
 text(copy,'strong',passengerTitle(booking));
 text(copy,'small',[days.length>1?days[0]+' ~ '+days.at(-1):days[0],route||'여정 미확인',booking.conflict?'자료 충돌':booking.cancelled?'취소·변경 자료':''].filter(Boolean).join(' · '));
 item.addEventListener('toggle',()=>{if(item.open){resultRoot.querySelectorAll('.fb-booking-choice').forEach(other=>{if(other!==item)other.open=false});ticket.querySelector('.fb-date-filter')?.dispatchEvent(new Event('fb-visible'))}});item.append(ticket);group.list.append(item)
 }else group.list.append(ticket)}
updateGroups();
sourceRevision=data.revision;nextOffset=data.next_offset??null;more.hidden=nextOffset===null;
const count=resultRoot.querySelectorAll('.fb-ticket').length;
status.textContent=data.source_status==='UNAVAILABLE'?'최근 항공권 자료를 확인할 수 없습니다. 잠시 후 예약 조회를 눌러 다시 시도하세요.':count?(data.total??count)===count?'예약 '+count+'건':'예약 '+count+' / '+data.total+'건':'검색 조건에 맞는 항공권 예약이 없습니다. 탑승객 이름·행선지·날짜를 바꿔 검색하세요.';
}catch(error){status.textContent=error.name==='AbortError'?'항공권 조회 응답이 지연되고 있습니다. 예약 조회를 눌러 다시 시도해 주세요.':error.message}finally{clearTimeout(requestTimer);if(!waiting){submit.disabled=false;more.disabled=false;resultRoot.setAttribute('aria-busy','false')}}}
form.addEventListener('submit',e=>{e.preventDefault();if(submit.disabled)return;clearTimeout(refreshTimer);refreshAttempts=0;refreshStarted=Date.now();searchName=form.elements.name.value.trim();loadBookings(true)});
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
        row = {key: card.get(key) for key in ('transaction_id', 'approval_date', 'merchant', 'issuer', 'card_tail',
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
    """Search evidenced names, routes and travel dates without a tour or booking ID."""
    from .flight_booking_search import parse_search
    query, dates = parse_search(name, _name_key)
    if type(offset) is not int or offset < 0 or offset > 1000000 or offset and not revision:
        raise ValueError('INVALID_CURSOR')
    from .flight_booking_index import passenger_index_for, source_status
    from .flight_booking_projection import query_booking_reservations
    index = passenger_index_for(board)
    cards = _confirmed_card_index(board, index)
    trip_metadata, trip_revision = _search_trip_metadata(board, index, cards)
    return query_booking_reservations(
        index,
        query_tokens=query,
        query_dates=dates,
        cards=cards,
        offset=offset,
        revision=revision,
        fallback_status_fn=lambda: source_status(board),
        name_key_fn=_name_key,
        trip_metadata=trip_metadata,
        trip_revision=trip_revision,
    )


def _search_trip_metadata(board, index, cards):
    """Reuse the ledger's read-only booking assignment projection; never save assignments."""
    from . import trip_flight_read
    getter = getattr(board, 'live_trips', None) or getattr(board, 'list_trips', None)
    unavailable = {(str(e.get('provider') or 'trip').lower(), str(ref)):
                   {'trip_assignment_available': False}
                   for ref, e in index.items() if isinstance(e, dict)}
    if not callable(getter):
        return unavailable, 'TRIP_AUTHORITY_UNAVAILABLE'
    try:
        trips = list(getter(include_archived=True))
        rules = trip_flight_read.read_booking_trip_rules()
        rows = trip_flight_read.confirmed_card_trip_rows(board, cards)
        manual, authorities, authority_revision = trip_flight_read.build_authority_maps(
            index, trips, booking_trip_rules=rules, confirmed_card_links=cards, expense_rows=rows)
        projection = trip_flight_read.project_trip_bookings(index, trips,
            source_generation=authority_revision, user_assignments=manual,
            authority_trip_ids=authorities)
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error):
        return unavailable, 'TRIP_AUTHORITY_UNAVAILABLE'
    by_id = {str(t.get('tab_id')): t for t in trips}
    metadata = {}
    for booking in projection['bookings']:
        tab_id = booking['assigned_trip_tab_id']
        trip = by_id.get(tab_id, {})
        metadata[(booking['provider'], booking['booking_ref'])] = {
            'assigned_trip_tab_id': tab_id,
            'assigned_trip_title': str(trip.get('display_title') or trip.get('display_key')
                                       or trip.get('title') or tab_id),
            'assigned_trip_starts_on': str(trip.get('starts_on') or trip.get('start_on') or ''),
            'assignment_status': booking['assignment_status'],
            'assignment_basis': booking['assignment_basis'],
            'assignment_conflict': booking['assignment_conflict'],
            'trip_assignment_available': True,
        }
    # Include titles as well as authority revisions in pagination's stale-source boundary.
    digest = hashlib.sha256(json.dumps([authority_revision, sorted(metadata.items())],
        sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    return metadata, digest


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
