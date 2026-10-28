"""Escaped, lazy trip-flight section markup and client pagination."""
from html import escape


def render_flight_section(trip_tab_id: str, *, total: int = 0, passenger_count: int = 0,
                          endpoint: str = "") -> str:
    trip = escape(str(trip_tab_id), quote=True)
    url = escape(endpoint or f"/api/trips/{trip}/flight-bookings", quote=True)
    return (f'<section class="trip-flight" data-trip="{trip}" data-endpoint="{url}">'
            f'<details><summary>항공권 예약 {int(total)}건 · 확인된 탑승객 {int(passenger_count)}명</summary>'
            '<p class="trip-flight-status" role="status">펼치면 예약 목록을 불러옵니다.</p>'
            '<ol class="trip-flight-items"></ol><button type="button" class="trip-flight-more" hidden>다음</button>'
            '</details></section>')


CLIENT_SCRIPT = r"""<script>
document.querySelectorAll('.trip-flight').forEach(section=>{
 const details=section.querySelector('details'), status=section.querySelector('.trip-flight-status'), list=section.querySelector('.trip-flight-items'), more=section.querySelector('.trip-flight-more');
 let loaded=false,cursor='';
 async function load(){status.textContent='예약 목록을 불러오는 중입니다.';const u=new URL(section.dataset.endpoint,location.origin);if(cursor)u.searchParams.set('cursor',cursor);try{const r=await fetch(u,{headers:{Accept:'application/json'}}),d=await r.json();if(!r.ok)throw Error(d.code||'UNAVAILABLE');for(const b of d.items||[]){const li=document.createElement('li'),title=document.createElement('strong'),meta=document.createElement('p');title.textContent=(b.outbound_departure_on||'출발일 미확인')+' · '+(b.booking_ref||'예약번호 미확인');const seg=(b.legs||[]).flatMap(x=>x.segments||[]);meta.textContent=seg.map(x=>(x.departure_airport||'?')+' → '+(x.arrival_airport||'?')).join(' · ')+' · '+b.passenger_count+'명 · '+b.assignment_status;li.append(title,meta);list.append(li)}cursor=d.next_cursor||'';more.hidden=!cursor;status.textContent=d.evidence_status==='UNAVAILABLE'?'항공권 자료를 확인할 수 없습니다.':d.items.length?'예약 '+d.total_bookings+'건':'확인된 예약이 없습니다.';loaded=true}catch(e){status.textContent='예약 자료를 불러오지 못했습니다.'}}
 details.addEventListener('toggle',()=>{if(details.open&&!loaded)load()});more.addEventListener('click',load);
});
</script>"""
