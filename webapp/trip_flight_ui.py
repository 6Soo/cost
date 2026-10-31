"""Escaped, lazy trip-flight section markup and client pagination."""
from html import escape
from urllib.parse import quote


def render_flight_section(trip_tab_id: str, *, total: int | None = None, passenger_count: int | None = None,
                          endpoint: str = "") -> str:
    trip = escape(str(trip_tab_id), quote=True)
    encoded_trip = quote(str(trip_tab_id), safe="")
    url = escape(endpoint or f"/api/trips/{encoded_trip}/flight-bookings", quote=True)
    summary = ("항공권 예약" if total is None else
               f"항공권 예약 {int(total)}건" + (f" · 확인된 탑승객 {int(passenger_count)}명" if passenger_count is not None else ""))
    return (f'<section class="trip-flight" data-trip="{trip}" data-endpoint="{url}">'
            f'<details><summary>{summary}</summary>'
            '<p class="trip-flight-status" role="status">펼치면 예약 목록을 불러옵니다.</p>'
            '<button type="button" class="trip-flight-retry" hidden>다시 불러오기</button>'
            '<ol class="trip-flight-items"></ol><button type="button" class="trip-flight-more" hidden>다음</button>'
            '</details></section>')


def render_trip_flights(trip_tab_id: str, *, total: int | None = None,
                        passenger_count: int | None = None, endpoint: str = "") -> str:
    """Public ledger page hook: initial collapsed HTML plus lazy detail client."""
    return render_flight_section(trip_tab_id, total=total,
                                 passenger_count=passenger_count, endpoint=endpoint) + CLIENT_SCRIPT


CLIENT_SCRIPT = r"""<script>
document.querySelectorAll('.trip-flight').forEach(section=>{
 const details=section.querySelector('details'), status=section.querySelector('.trip-flight-status'), list=section.querySelector('.trip-flight-items'), more=section.querySelector('.trip-flight-more');
 const retry=section.querySelector('.trip-flight-retry');let retryAction=null;retry.addEventListener('click',()=>retryAction?.());
 let loaded=false,busy=false,cursor='',generation='';
 function resetSource(){loaded=false;cursor='';generation='';list.replaceChildren();more.hidden=true;section.querySelector('.trip-flight-detail')?.remove();}
 async function load(){if(busy)return;retry.hidden=true;busy=true;more.disabled=true;status.textContent='예약 목록을 불러오는 중입니다.';const u=new URL(section.dataset.endpoint,location.origin);if(cursor)u.searchParams.set('cursor',cursor);try{const r=await fetch(u,{headers:{Accept:'application/json'}}),d=await r.json();if(!r.ok)throw Error(d.code||'UNAVAILABLE');if(generation&&generation!==d.source_generation)throw Error('SOURCE_CHANGED');generation=d.source_generation;for(const b of d.items||[]){const li=document.createElement('li'),title=document.createElement('button'),meta=document.createElement('p');title.type='button';title.textContent=(b.outbound_departure_on||'출발일 미확인')+' · '+(b.booking_ref||'예약번호 미확인');title.addEventListener('click',()=>loadDetail(b.booking_key));meta.textContent=(b.route_summary||'경로 확인 필요')+' · '+b.passenger_count+'명 · '+b.assignment_status+(b.assignment_conflict?' · 귀속 충돌':'')+(b.evidence_status==='CONFLICT'?' · 자료 충돌':'');li.append(title,meta);list.append(li)}cursor=d.next_cursor||'';more.hidden=!cursor;status.textContent=d.evidence_status==='UNAVAILABLE'?'항공권 자료를 확인할 수 없습니다.':d.items.length?'예약 '+d.total_bookings+'건':'확인된 예약이 없습니다.';loaded=true}catch(e){if(e.message==='SOURCE_CHANGED')resetSource();retryAction=load;retry.hidden=false;status.textContent=e.message==='SOURCE_CHANGED'?'예약 자료가 갱신됐습니다. 목록을 새로 열어 주세요.':'예약 자료를 불러오지 못했습니다.'}finally{busy=false;more.disabled=false}}
 async function loadDetail(key){retry.hidden=true;const u=new URL(section.dataset.endpoint,location.origin);u.searchParams.set('booking_key',key);if(generation)u.searchParams.set('generation',generation);status.textContent='예약 상세를 불러오는 중입니다.';try{const r=await fetch(u,{headers:{Accept:'application/json'}}),d=await r.json();if(!r.ok)throw Error(d.code||'UNAVAILABLE');const b=d.item;let detail=section.querySelector('.trip-flight-detail');if(!detail){detail=document.createElement('div');detail.className='trip-flight-detail';section.append(detail)}detail.replaceChildren();const heading=document.createElement('h3');heading.textContent=(b.booking_ref||'예약번호 미확인')+' · '+b.passengers.length+'명';detail.append(heading);for(const leg of b.legs||[]){const p=document.createElement('p');p.textContent=(leg.label||'여정')+' · '+(leg.departure_on||'날짜 미확인')+' · '+(leg.segments||[]).map(x=>(x.departure_airport||'?')+' → '+(x.arrival_airport||'?')+' '+(x.flight_number||'')).join(' · ');detail.append(p)}const names=document.createElement('p');names.textContent=b.passengers.join(', ');detail.append(names);if(b.booking_date_label){const booked=document.createElement('p');booked.textContent=b.booking_date_label;detail.append(booked)}status.textContent='예약 상세를 표시합니다.'}catch(e){if(e.message==='SOURCE_CHANGED')resetSource();retryAction=e.message==='SOURCE_CHANGED'?load:()=>loadDetail(key);retry.hidden=false;status.textContent=e.message==='SOURCE_CHANGED'?'예약 자료가 갱신됐습니다. 목록을 새로 열어 주세요.':'예약 상세를 불러오지 못했습니다.'}}
 details.addEventListener('toggle',()=>{if(details.open&&!loaded)load()});more.addEventListener('click',load);
});
</script>"""
