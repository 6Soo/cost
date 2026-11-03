"""Escaped, lazy trip-flight section markup and client pagination."""
from html import escape
from urllib.parse import quote


def render_flight_section(trip_tab_id: str, *, total: int | None = None, passenger_count: int | None = None,
                          endpoint: str = "") -> str:
    trip = escape(str(trip_tab_id), quote=True)
    encoded_trip = quote(str(trip_tab_id), safe="")
    url = escape(endpoint or f"/api/trips/{encoded_trip}/flight-bookings", quote=True)
    summary = ("항공권 예약" if total is None else
               f"항공권 예약 {int(total)}건" + (f" · 현재 예약 탑승객 {int(passenger_count)}명" if passenger_count is not None else ""))
    return (f'<section class="trip-flight" data-trip="{trip}" data-endpoint="{url}">'
            f'<details><summary>{summary}</summary>'
            '<div class="trip-flight-body">'
            '<p class="trip-flight-status" role="status" aria-live="polite">펼치면 예약 목록을 불러옵니다.</p>'
            '<label class="trip-flight-filter">예약 상태 <select aria-label="예약 상태">'
            '<option value="active">현재 예약</option><option value="all">전체 이력 (취소 포함)</option>'
            '</select></label>'
            '<button type="button" class="trip-flight-retry" hidden>다시 불러오기</button>'
            '<ol class="trip-flight-items"></ol><button type="button" class="trip-flight-more" hidden>예약 더 보기</button>'
            '<div class="trip-flight-detail" tabindex="-1" hidden></div>'
            '</div></details></section>')


def render_trip_flights(trip_tab_id: str, *, total: int | None = None,
                        passenger_count: int | None = None, endpoint: str = "") -> str:
    """Public ledger page hook: initial collapsed HTML plus lazy detail client."""
    return render_flight_section(trip_tab_id, total=total,
                                 passenger_count=passenger_count, endpoint=endpoint) + STYLE + CLIENT_SCRIPT


STYLE = """<style>
.trip-flight{margin:20px 0;border:1px solid var(--line,#d6dce3);border-radius:12px;background:var(--paper,#fff);color:var(--ink,#172b42);font:inherit;overflow:hidden}
.trip-flight summary{padding:16px;min-height:44px;box-sizing:border-box;font-weight:600;cursor:pointer}
.trip-flight summary:hover{background:var(--hover,#f4f6f8)}
.trip-flight-body{padding:0 16px 16px}
.trip-flight-filter{display:flex;align-items:center;gap:8px;margin:0 0 12px;flex-wrap:wrap}
.trip-flight-filter select{font:inherit;color:inherit;background:var(--paper,#fff);border:1px solid var(--line,#d6dce3);border-radius:8px;min-height:44px;max-width:100%;padding:8px}
.trip-flight-filter select:focus-visible{outline:2px solid var(--grn,#176b59);outline-offset:2px}
.trip-flight-status{margin:0 0 12px;line-height:1.6;font-size:13px;color:var(--mut,#536375)}
.trip-flight[data-state=error] .trip-flight-status{color:var(--ink,#172b42);padding:12px;border-left:3px solid var(--mut,#536375);background:var(--bg,#f4f6f8);border-radius:4px}
.trip-flight button{font:inherit;color:inherit;min-height:44px;cursor:pointer;border:1px solid var(--line,#d6dce3);border-radius:8px;background:var(--paper,#fff);padding:10px 14px;max-width:100%;overflow-wrap:anywhere;text-align:left}
.trip-flight button:hover{background:var(--hover,#f4f6f8)}
.trip-flight button:disabled{opacity:.6;cursor:wait}
.trip-flight :is(button,summary):focus-visible{outline:2px solid var(--grn,#176b59);outline-offset:-3px}
.trip-flight-items{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.trip-flight-items li{min-width:0;border:1px solid var(--line,#d6dce3);border-radius:8px;padding:12px;background:var(--paper,#fff)}
.trip-flight-items button{font-weight:600;width:100%;border:0;padding:4px 0}
.trip-flight-items p{margin:4px 0 0;font-size:13px;line-height:1.6;color:var(--mut,#536375);overflow-wrap:anywhere}
.trip-flight-more{margin-top:12px}
.trip-flight-detail{margin-top:16px;padding:16px;background:var(--bg,#f4f6f8);border:1px solid var(--line,#d6dce3);border-radius:8px;overflow-wrap:anywhere}
.trip-flight-detail h3{font-size:15px;margin:0 0 12px}
.trip-flight-detail p{font-size:13px;line-height:1.7;margin:8px 0}
.trip-flight [hidden]{display:none!important}
@media(max-width:480px){.trip-flight-body{padding:0 12px 12px}.trip-flight summary{padding:14px 12px}.trip-flight-detail{padding:12px}}
</style>"""


CLIENT_SCRIPT = r"""<script>
document.querySelectorAll('.trip-flight').forEach(section=>{
 if(section.dataset.initialized)return;section.dataset.initialized='true';
 const details=section.querySelector('details'), status=section.querySelector('.trip-flight-status'), list=section.querySelector('.trip-flight-items'), more=section.querySelector('.trip-flight-more'), retry=section.querySelector('.trip-flight-retry'), detail=section.querySelector('.trip-flight-detail'), filter=section.querySelector('.trip-flight-filter select');
 let loaded=false,busy=false,cursor='',generation='',retryAction=null;
 const labels={AUTO_INFERRED:'출발일 기준 자동 배정',USER_CONFIRMED:'수동 배정',AUTHORITY_VERIFIED:'연결 근거로 배정',VERIFIED_GUIDE_BRIDGE:'가이드 예약 근거',UNRESOLVED:'배정 근거 확인 필요',CONFLICT:'귀속 충돌'};
 function setBusy(value){busy=value;section.setAttribute('aria-busy',String(value));more.disabled=value;retry.disabled=value;filter.disabled=value;list.querySelectorAll('button').forEach(b=>b.disabled=value)}
 function message(value,state='ready'){status.textContent=value;section.dataset.state=state}
 function resetSource(){loaded=false;cursor='';generation='';list.replaceChildren();more.hidden=true;detail.replaceChildren();detail.hidden=true;section.querySelector('summary').textContent='항공권 예약'}
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
   const d=await request(u);if(generation&&generation!==d.source_generation)throw Error('SOURCE_CHANGED');generation=d.source_generation;
   for(const b of d.items||[]){const li=document.createElement('li');const title=append(li,'button',(b.outbound_departure_on||'출발일 미확인')+' · '+(b.booking_ref||'예약번호 미확인'));title.type='button';title.addEventListener('click',()=>loadDetail(b.booking_key));
    append(li,'p',(b.route_summary||'경로 확인 필요')+' · '+(b.passenger_count??0)+'명');append(li,'p',assignment(b)+(b.booking_status==='CANCELLED'?' · 취소':b.booking_status==='CONFLICT'?' · 예약 상태 충돌':''));list.append(li)}
   cursor=d.next_cursor||'';more.hidden=!cursor;
   section.querySelector('summary').textContent='항공권 예약 '+d.total_bookings+'건'+(d.verified_passenger_count!=null?' · 현재 예약 탑승객 '+d.verified_passenger_count+'명':'');
   message(d.evidence_status==='UNAVAILABLE'?'항공권 자료를 확인할 수 없습니다.':d.total_bookings?'예약 '+d.total_bookings+'건 중 '+list.children.length+'건 · 예약을 선택하면 여정과 탑승객을 확인할 수 있습니다.':'이 여행에 연결된 항공권 예약이 없습니다.');loaded=true;
  }catch(e){failed(e,load,'예약 자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')}finally{setBusy(false)}
 }
 async function loadDetail(key){
  if(busy)return;retry.hidden=true;setBusy(true);detail.hidden=true;
  const u=new URL(section.dataset.endpoint,location.origin);u.searchParams.set('booking_key',key);if(generation)u.searchParams.set('generation',generation);
  message('예약 상세를 불러오는 중입니다.','loading');
  try{const d=await request(u),b=d.item;detail.replaceChildren();
   append(detail,'h3',(b.booking_ref||'예약번호 미확인')+' · '+(b.passengers||[]).length+'명');
   for(const leg of b.legs||[])append(detail,'p',(leg.label||'여정')+' · '+(leg.departure_on||'날짜 미확인')+' · '+(leg.segments||[]).map(x=>(x.departure_airport||'?')+' → '+(x.arrival_airport||'?')+' '+(x.flight_number||'')+' '+[x.departure_time,x.arrival_time].filter(Boolean).join('–')).join(' · '));
   append(detail,'p','탑승객: '+((b.passengers||[]).join(', ')||'확인 필요'));
   if(b.booking_date_label)append(detail,'p',b.booking_date_label);
   append(detail,'p',assignment(b)+(b.booking_status==='CANCELLED'?' · 취소':b.booking_status==='CONFLICT'?' · 예약 상태 충돌':''));detail.hidden=false;detail.focus();message('예약 상세를 표시합니다.');
  }catch(e){failed(e,()=>loadDetail(key),'예약 상세를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')}finally{setBusy(false)}
 }
 retry.addEventListener('click',()=>retryAction?.());
 filter.addEventListener('change',()=>{resetSource();retry.hidden=true;if(details.open)load()});
 details.addEventListener('toggle',()=>{if(details.open&&!loaded)load()});more.addEventListener('click',load);
});
</script>"""
