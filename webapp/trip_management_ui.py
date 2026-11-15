"""Trip-local controls; writes retain the existing metadata handlers and guards."""
from urllib.parse import urlencode
from uuid import uuid4


def controls(board, trip):
    if not trip or trip.get('is_unclassified') or board.current_role() != 'owner':
        return ''
    from .sheets_export import _assignee_confirmed
    from . import ui_icons
    esc = board.esc
    tid = trip['tab_id']
    back = '/board?' + urlencode({'tab': tid})
    action = f"/api/trips/{esc(tid)}/meta"

    def hidden(name, value):
        return f"<input type='hidden' name='{name}' value='{esc(str(value))}'>"

    def form(fields, body, *, close=False):
        return (f"<form method='post' action='{action}' class='{'trip-close-form' if close else 'trip-info-form'}'>"
                + hidden('csrf', board.CSRF_TOKEN) + hidden('client_request_id', uuid4().hex)
                + hidden('return_to', back) + fields + body + '</form>')

    closed = bool(trip.get('visual_closed'))
    close_form = form(hidden('expected_closed', int(closed)) + hidden('visual_closed', int(not closed)),
                      f"<button class='btn' type='submit'>{ui_icons.icon('rotate-ccw' if closed else 'check')}{'마감 해제' if closed else '마감'}</button>", close=True)
    fields = hidden('expected_revision', trip.get('revision', 0))
    assignee = str(trip.get('prepared_by_name') or '')
    confirm = ''
    store = board._active_store()
    if assignee and not _assignee_confirmed(getattr(store, 'conn', None), tid,
                                           trip.get('assignee_source') or '', assignee):
        confirm = ("<label class='trip-assignee-confirm'><input type='checkbox' name='assignee_confirmed' value='1'>"
                   "이 담당자가 맞다고 확인해요</label>")
    inputs = ''.join(
        f"<label>{label}<input name='{key}' value='{esc(str(trip.get(key) or ''))}'{kind}></label>"
        for key, label, kind in [('display_key', '표시 이름', ''),
                                 ('prepared_by_name', '담당자', '')])
    edit = form(fields + hidden('assignee_form', '1'), inputs + confirm + "<button class='btn' type='submit'>정보 저장</button>")
    archive = form(fields + hidden('archived', int(not trip.get('archived'))),
                   f"<button class='btn' type='submit'>{'보관 해제' if trip.get('archived') else '보관'}</button>")
    # The old inline controls were visually equal to the ledger actions.  Keep
    # every existing form field and POST target, but put the secondary actions in
    # one disclosure menu in the trip header.
    return ("<details class='trip-more' id='trip-settings'>"
            "<summary class='icon-btn' data-no-action-icon aria-label='여행 작업' aria-expanded='false'>⋯<span class='sr'>여행 작업</span></summary>"
            "<div class='trip-more-menu'>"
            "<a class='btn' href='/export?" + esc(urlencode({'tab': tid})) + "'>XLSX 내보내기</a>"
            + close_form.replace("<form ", "<form id='trip-close' ", 1)
            + "<h3 class='trip-more-heading'>여행 정보 수정</h3>" + edit + archive
            + "<p class='muted'>마감은 COST의 표시 상태이며 Google 장부 이동·환급과는 별개입니다.</p>"
            + "</div></details>")


def reservations(board, trip):
    if not trip or trip.get('is_unclassified') or board.current_role() != 'owner':
        return ''
    url = '/reserve-links?' + urlencode({'trip': trip['tab_id'], 'embedded': '1'})
    return ("<details class='trip-reservations' id='trip-reservations'><summary>예약·참가자 여행 연결</summary>"
            "<p>이 여행의 예약 연결을 확인하거나, 미연결 예약을 찾아 여행을 선택하세요.</p>"
            f"<iframe title='이 여행 예약 연결' data-reservation-src='{board.esc(url)}'></iframe></details>")


STYLE = """
.drawer .p-hd h2,.drawer #p-close{display:none}
.trip-management-controls{display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap}
.page-hd>.act{flex:1 1 340px;max-width:100%;justify-content:flex-end}.page-hd{flex-wrap:wrap}
.trip-management-controls form{margin:0}.trip-management-controls button,.trip-settings>summary{min-height:44px}
.trip-settings{position:relative}.trip-settings>summary{margin:0;padding:10px 14px;border:1px solid var(--line);border-radius:var(--r-md);cursor:pointer}
.trip-settings>div{padding:16px;border:1px solid var(--line);border-radius:var(--r-md);background:var(--paper);width:min(360px,100%);box-sizing:border-box}
.trip-info-form{display:grid;gap:12px}.trip-info-form label{display:grid;gap:4px}
.trip-info-form input{min-width:0;max-width:100%;min-height:44px;box-sizing:border-box}
.trip-info-form .trip-assignee-confirm{display:flex;align-items:center;gap:8px}
.trip-settings .trip-info-form+form{margin-top:16px}
.trip-reservations{margin:20px 0;border:1px solid var(--line);border-radius:var(--r-lg);padding:12px;min-width:0}
.trip-reservations>summary{min-height:44px;cursor:pointer;font-weight:600}
.trip-reservations iframe{display:block;width:100%;min-height:240px;border:0}
@media(max-width:640px){.trip-management-controls{width:100%}.trip-settings{flex:1}.trip-settings>div{width:100%}}
.trip-management-controls details>summary{list-style:none}.trip-management-controls details>summary::-webkit-details-marker{display:none}
"""

SCRIPT = """
(function(){
  var details=document.getElementById('trip-reservations');
  if(!details)return;
  var frame=details.querySelector('iframe');
  frame.addEventListener('load',function(){
    try{
      var doc=frame.contentDocument;
      function resize(){frame.style.height=Math.ceil(doc.body.scrollHeight+24)+'px';}
      new ResizeObserver(resize).observe(doc.body);resize();
    }catch(e){frame.style.height='640px';}
  });
  function open(){if(details.open&&!frame.getAttribute('src'))frame.src=frame.dataset.reservationSrc;}
  details.addEventListener('toggle',open);
  function reveal(){if(location.hash==='#trip-reservations'){details.open=true;open();}}
  window.addEventListener('hashchange',reveal);reveal();
})();
"""
