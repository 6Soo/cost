"""Escaped, lazy trip-flight section markup and client pagination."""
from html import escape
from urllib.parse import quote

from . import ui_icons


def render_flight_section(trip_tab_id: str, *, total: int | None = None, passenger_count: int | None = None,
                          endpoint: str = "") -> str:
    trip = escape(str(trip_tab_id), quote=True)
    encoded_trip = quote(str(trip_tab_id), safe="")
    url = escape(endpoint or f"/api/trips/{encoded_trip}/flight-bookings", quote=True)
    summary = ("항공권 예약" if total is None else
               f"항공권 예약 {int(total)}건" + (f" · 현재 예약 탑승객 {int(passenger_count)}명" if passenger_count is not None else ""))
    return (f'<section class="trip-flight" data-trip="{trip}" data-endpoint="{url}">'
            f'<details><summary><span class="trip-flight-summary-icon">{ui_icons.icon("list", 16)}</span>'
            f'<span class="trip-flight-summary-label">{escape(summary)}</span>'
            f'<span class="trip-flight-summary-chevron">{ui_icons.icon("chevron-down", 16)}</span></summary>'
            '<div class="trip-flight-body">'
            '<p class="trip-flight-status" role="status" aria-live="polite">펼치면 예약 목록을 불러옵니다.</p>'
            '<div class="trip-flight-toolbar"><label class="trip-flight-filter">예약 상태 <select aria-label="예약 상태">'
            '<option value="active">현재 예약</option><option value="all">전체 이력 (취소 포함)</option>'
            '</select></label></div>'
            '<button type="button" class="trip-flight-retry" hidden>다시 불러오기</button>'
            '<div class="trip-flight-workspace"><div class="trip-flight-list"><ol class="trip-flight-items" aria-label="항공권 예약 목록"></ol><button type="button" class="trip-flight-more" hidden>예약 더 보기</button></div>'
            '<div class="trip-flight-detail" role="region" aria-label="선택한 예약 상세" tabindex="-1" hidden></div></div>'
            '</div></details></section>')


def render_trip_flights(trip_tab_id: str, *, total: int | None = None,
                        passenger_count: int | None = None, endpoint: str = "") -> str:
    """Public ledger page hook: initial collapsed HTML plus lazy detail client."""
    return render_flight_section(trip_tab_id, total=total,
                                 passenger_count=passenger_count, endpoint=endpoint) + STYLE + CLIENT_SCRIPT


STYLE = """<style>
@import url('/static/css/tokens.css');
.trip-flight{margin:20px 0;border:1px solid var(--line,var(--c-border));border-radius:var(--r-lg);background:var(--paper,var(--c-surface));color:var(--ink,var(--c-text));font:inherit;container-type:inline-size}
.trip-flight>details>summary{display:flex;align-items:center;gap:12px;width:100%;margin:0;padding:16px 20px;min-height:56px;box-sizing:border-box;border:0;border-radius:var(--r-lg);font-size:var(--t-body-sm);font-weight:650;cursor:pointer;list-style:none;overflow-wrap:anywhere}
.trip-flight summary::-webkit-details-marker{display:none}
.trip-flight>details>summary::marker{content:""}
.trip-flight-summary-icon,.trip-flight-summary-chevron{display:inline-flex;align-items:center;justify-content:center;flex:0 0 16px;color:var(--mut,var(--c-text-secondary))}
.trip-flight-summary-label{min-width:0;flex:1;overflow-wrap:anywhere}
.trip-flight>details[open]>summary .trip-flight-summary-chevron{transform:rotate(180deg)}
.trip-flight-body{padding:0 20px 20px;min-width:0}
.trip-flight-toolbar{display:flex;justify-content:flex-end;margin-block-end:12px}
.trip-flight-filter{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:var(--t-meta);color:var(--mut,var(--c-text-secondary));margin:0}
.trip-flight-filter select{font:inherit;font-size:var(--t-body);color:var(--ink,var(--c-text));background:var(--paper,var(--c-surface));border:1px solid var(--line,var(--c-border));border-radius:var(--r-md);min-height:44px;max-width:100%;padding:8px 12px}
.trip-flight-status{margin:0 0 12px;line-height:1.6;font-size:var(--t-meta);color:var(--mut,var(--c-text-secondary))}
.trip-flight[data-state=ready] .trip-flight-status:not(:empty){position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.trip-flight[data-state=empty] .trip-flight-status,.trip-flight[data-state=error] .trip-flight-status{padding:16px;background:var(--bg,var(--c-surface-sunken));border-radius:var(--r-md);color:var(--ink,var(--c-text))}
.trip-flight button{font:inherit;color:inherit;min-height:44px;cursor:pointer;border:1px solid var(--line,var(--c-border));border-radius:var(--r-md);background:var(--paper,var(--c-surface));padding:10px 14px;max-width:100%;overflow-wrap:anywhere;text-align:start;white-space:normal}
.trip-flight button:disabled{opacity:.65;cursor:wait}
.trip-flight :is(button,summary,select):focus-visible,.trip-flight-detail:focus-visible{outline:2px solid var(--focus,var(--c-focus,Highlight));outline-offset:-3px}
.trip-flight-workspace{display:grid;gap:16px;align-items:start}
.trip-flight-list{min-width:0}
.trip-flight-items{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.trip-flight .trip-flight-items li{min-width:0;padding:0;border:0;background:none}
.trip-flight .trip-flight-items button{display:grid;gap:6px;width:100%;height:auto;justify-content:stretch;padding:12px 16px;border:1px solid var(--line,var(--c-border));border-radius:var(--r-md);font-weight:400;line-height:1.5}
.trip-flight .trip-flight-items button[aria-pressed=true]{border-color:var(--focus,var(--c-focus,Highlight));box-shadow:inset 3px 0 var(--focus,var(--c-focus,Highlight));background:var(--hover,var(--c-surface-sunken))}
.trip-flight-route{display:flex;justify-content:space-between;align-items:baseline;gap:12px;font-size:var(--t-body);font-weight:650}
.trip-flight-meta{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:var(--t-meta);color:var(--mut,var(--c-text-secondary));font-variant-numeric:tabular-nums}
.trip-flight-ref{font-size:var(--t-caption);color:var(--mut,var(--c-text-secondary));overflow-wrap:anywhere}
.trip-flight-choice{font-size:var(--t-caption);font-weight:600;color:var(--ink,var(--c-text));flex-shrink:0}
.trip-flight-more{margin-top:12px;width:100%}
.trip-flight-detail{min-width:0;padding:20px;background:var(--bg,var(--c-surface-sunken));border:1px solid var(--line,var(--c-border));border-radius:var(--r-lg);overflow-wrap:anywhere;scroll-margin-block:20px}
.trip-flight .trip-flight-detail h3{font-size:var(--t-body);line-height:1.5;margin:0 0 16px;font-weight:650}
.trip-flight-legs{display:grid;gap:8px;margin-block-end:16px}
.trip-flight-leg{padding:12px 14px;border:1px solid var(--line,var(--c-border));border-radius:var(--r-md);background:var(--paper,var(--c-surface))}
.trip-flight .trip-flight-detail p{font-size:var(--t-meta);line-height:1.7;margin:6px 0;color:var(--ink,var(--c-text))}
.trip-flight .trip-flight-leg h4{font-size:var(--t-meta);font-weight:600;margin:0 0 6px;color:var(--mut,var(--c-text-secondary))}
.trip-flight .trip-flight-leg .trip-flight-leg-route{font-size:var(--t-h3);font-weight:650;margin:0}
.trip-flight-detail-meta{padding-block-start:12px;border-top:1px solid var(--line,var(--c-border))}
.trip-flight .trip-flight-detail .trip-flight-note{font-size:var(--t-caption);color:var(--mut,var(--c-text-secondary))}
.trip-flight [hidden]{display:none!important}
@media(hover:hover){.trip-flight>details>summary:hover,.trip-flight button:hover{background:var(--hover,var(--c-surface-sunken))}}
@container(min-width:760px){.trip-flight-workspace:has(.trip-flight-detail:not([hidden])){grid-template-columns:minmax(260px,2fr) minmax(0,3fr)}.trip-flight-workspace:not(:has(.trip-flight-detail:not([hidden]))) .trip-flight-items{grid-template-columns:repeat(3,minmax(0,1fr))}}
@container(max-width:480px){.trip-flight-body{padding:0 12px 12px}.trip-flight>details>summary{padding:14px 12px}.trip-flight-detail{padding:14px}.trip-flight-toolbar{justify-content:flex-start}}
</style>"""


CLIENT_SCRIPT = r"""<script>
document.querySelectorAll('.trip-flight').forEach(section=>{
 if(section.dataset.initialized)return;section.dataset.initialized='true';
 const details=section.querySelector('details'), status=section.querySelector('.trip-flight-status'), list=section.querySelector('.trip-flight-items'), more=section.querySelector('.trip-flight-more'), retry=section.querySelector('.trip-flight-retry'), detail=section.querySelector('.trip-flight-detail'), filter=section.querySelector('.trip-flight-filter select');
 let loaded=false,busy=false,cursor='',generation='',retryAction=null,selectedKey='';
 const labels={AUTO_INFERRED:'출발일 기준 자동 배정',USER_CONFIRMED:'수동 배정',AUTHORITY_VERIFIED:'연결 근거로 배정',VERIFIED_GUIDE_BRIDGE:'가이드 예약 근거',UNRESOLVED:'배정 근거 확인 필요',CONFLICT:'귀속 충돌'};
 function setBusy(value){busy=value;section.setAttribute('aria-busy',String(value));more.disabled=value;retry.disabled=value;filter.disabled=value;list.querySelectorAll('button').forEach(b=>b.disabled=value)}
 function message(value,state='ready'){status.textContent=value;section.dataset.state=state}
 function setSummary(value){section.querySelector('.trip-flight-summary-label').textContent=value}
 function resetSource(){selectedKey='';loaded=false;cursor='';generation='';list.replaceChildren();more.hidden=true;detail.replaceChildren();detail.hidden=true;setSummary('항공권 예약')}
 function failed(e,action,fallback){
  if(e.message==='SOURCE_CHANGED')resetSource();
  retryAction=e.message==='SOURCE_CHANGED'?load:action;retry.hidden=false;
  const messages={SOURCE_CHANGED:'예약 자료가 갱신됐습니다. 목록을 새로 열어 주세요.',FLIGHT_AUTHORITY_UNAVAILABLE:'예약의 여행 배정 자료를 확인할 수 없습니다. 잠시 후 다시 불러와 주세요.',FLIGHT_SOURCE_UNAVAILABLE:'항공권 자료를 준비 중이거나 수집 상태를 확인할 수 없습니다. 잠시 후 다시 불러와 주세요.',TRIP_NOT_FOUND:'이 여행의 예약을 조회할 수 없습니다. 여행 목록과 접근 권한을 확인해 주세요.',AUTH_REQUIRED:'로그인이 필요합니다. 새로고침 후 로그인해 주세요.'};
  message(messages[e.message]||fallback,'error');
 }
 async function request(u){const r=await fetch(u,{headers:{Accept:'application/json'}});if(r.status===401||r.redirected)throw Error('AUTH_REQUIRED');const d=await r.json();if(!r.ok)throw Error(d.code||'UNAVAILABLE');return d}
 function append(parent,tag,value){const node=document.createElement(tag);node.textContent=value;parent.append(node);return node}
 function assignment(b){return (labels[b.assignment_status]||'배정 근거 확인 필요')+(b.assignment_conflict?' · 귀속 충돌':'')+(b.evidence_status==='CONFLICT'?' · 자료 충돌':'')}
 async function load(){
  if(busy)return;retry.hidden=true;setBusy(true);message('예약 목록을 불러오는 중입니다.','loading');
  const u=new URL(section.dataset.endpoint,location.origin);u.searchParams.set('status',filter.value);if(cursor)u.searchParams.set('cursor',cursor);
  try{
   const d=await request(u);if(d.evidence_status==='UNAVAILABLE')throw Error('FLIGHT_SOURCE_UNAVAILABLE');if(generation&&generation!==d.source_generation)throw Error('SOURCE_CHANGED');generation=d.source_generation;
   for(const b of d.items||[]){const li=document.createElement('li'),title=append(li,'button','');title.type='button';title.dataset.bookingKey=b.booking_key;title.setAttribute('aria-pressed',String(b.booking_key===selectedKey));
    const date=b.outbound_departure_on||'출발일 미확인',ref=b.booking_ref||'예약번호 미확인';title.setAttribute('aria-label',date+' · '+ref+' · '+(b.route_summary||'경로 확인 필요')+' · '+(b.passenger_count??0)+'명 · 상세 보기');
    const route=append(title,'span','');route.className='trip-flight-route';append(route,'span',b.route_summary||'경로 확인 필요');append(route,'span',b.booking_key===selectedKey?'선택됨':'상세 보기').className='trip-flight-choice';
    const meta=append(title,'span','');meta.className='trip-flight-meta';append(meta,'span',date);append(meta,'span',(b.passenger_count??0)+'명');
    const foot=append(title,'span','');foot.className='trip-flight-meta';append(foot,'span','예약번호 '+ref);
    append(foot,'span',assignment(b)+(b.booking_status==='CANCELLED'?' · 취소':b.booking_status==='CONFLICT'?' · 예약 상태 충돌':'')).className='trip-flight-ref';
    title.addEventListener('click',()=>loadDetail(b.booking_key));list.append(li)}
   cursor=d.next_cursor||'';more.hidden=!cursor;
   setSummary('항공권 예약 '+d.total_bookings+'건'+(d.verified_passenger_count!=null?' · 현재 예약 탑승객 '+d.verified_passenger_count+'명':''));
   message(d.total_bookings?'예약 '+d.total_bookings+'건 중 '+list.children.length+'건 · 예약을 선택하면 여정과 탑승객을 확인할 수 있습니다.':'이 여행에 연결된 항공권 예약이 없습니다.',d.total_bookings?'ready':'empty');loaded=true;
  }catch(e){failed(e,load,'예약 자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')}finally{setBusy(false)}
 }
 async function loadDetail(key){
  if(busy)return;retry.hidden=true;setBusy(true);detail.hidden=true;
  const u=new URL(section.dataset.endpoint,location.origin);u.searchParams.set('booking_key',key);if(generation)u.searchParams.set('generation',generation);
  message('예약 상세를 불러오는 중입니다.','loading');
  try{const d=await request(u),b=d.item;detail.replaceChildren();
   append(detail,'h3',(b.booking_ref||'예약번호 미확인')+' · '+(b.passengers||[]).length+'명');
   const legs=append(detail,'div','');legs.className='trip-flight-legs';
   for(const leg of b.legs||[]){const card=append(legs,'div','');card.className='trip-flight-leg';append(card,'h4',(leg.label||'여정')+' · '+(leg.departure_on||'날짜 미확인'));
    for(const segment of leg.segments||[]){append(card,'p',(segment.departure_airport||'?')+' → '+(segment.arrival_airport||'?')).className='trip-flight-leg-route';append(card,'p',(segment.flight_number||'편명 미확인')+' · '+([segment.departure_time,segment.arrival_time].filter(Boolean).join('–')||'시간 미확인'))}
   }
   const meta=append(detail,'div','');meta.className='trip-flight-detail-meta';append(meta,'p','탑승객: '+((b.passengers||[]).join(', ')||'확인 필요'));
   if(b.booking_date_label)append(meta,'p',b.booking_date_label).className='trip-flight-note';
   append(meta,'p',assignment(b)+(b.booking_status==='CANCELLED'?' · 취소':b.booking_status==='CONFLICT'?' · 예약 상태 충돌':'')).className='trip-flight-note';
   selectedKey=key;list.querySelectorAll('button').forEach(button=>{const selected=button.dataset.bookingKey===key;button.setAttribute('aria-pressed',String(selected));button.querySelector('.trip-flight-choice').textContent=selected?'선택됨':'상세 보기'});
   detail.hidden=false;detail.focus();message('예약 상세를 표시합니다.');
  }catch(e){failed(e,()=>loadDetail(key),'예약 상세를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')}finally{setBusy(false)}
 }
 retry.addEventListener('click',()=>retryAction?.());
 filter.addEventListener('change',()=>{resetSource();retry.hidden=true;if(details.open)load()});
 details.addEventListener('toggle',()=>{if(details.open&&!loaded)load()});more.addEventListener('click',load);
});
</script>"""
