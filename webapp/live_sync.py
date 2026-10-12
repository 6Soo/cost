"""Live cross-screen refresh for the web ledger board.

One server and one database serve every screen, so a row saved in one browser is
already in the database when another browser looks. What was missing is the other
browser noticing. This module is the noticing: a stable token derived from the
data a caller may read, a cheap read endpoint that reports whether that token
moved, the page fragments to re-render when it did, and the browser script that
does the asking.

Four rules shape the whole thing.

1. The token is derived from the database, not from a counter in memory. A
   server restart therefore produces the same token for the same data, so a
   restart never looks like an edit and never discards an open draft.

2. The token is derived from the rows, trips and allocations the *caller* may
   read. A viewer's token is computed over the viewer's own trips only, so a save
   in a trip the viewer may not read cannot move the viewer's token. There is no
   global change count anywhere on this path, because a global count would tell a
   viewer that something happened which it is not allowed to see.

3. A refresh never overwrites an edit. An unsaved draft, a save in flight, an open
   panel, keyboard focus inside a field, or a scroll position the user chose: while
   any of those hold, the change is recorded as pending and the screen says so. It
   is applied when the edit is saved or cancelled, and the expected_revision
   conflict path is untouched, so the store still refuses a stale save.

4. Every answer is `Cache-Control: no-store`, so a browser or proxy cannot answer a
   later poll from a copy of an earlier one.
"""

from __future__ import annotations

import hashlib
import json

# APP_SPEC 15: an open board checks for a change about every two seconds, so a
# save in one browser is on the other one inside the five second budget. The
# interval is a floor, not a promise: a slow request pushes the next one out.
POLL_INTERVAL_MS = 2000

# A dropped connection backs off, but it is bounded. An unbounded backoff would
# look like a working screen that simply never updates, and a zero backoff would
# hammer a server that is down.
BACKOFF_START_MS = 2000
BACKOFF_CEILING_MS = 30000

# The token is a digest, not a number, and it is short enough to sit in a query
# string. Its length is not a security property: the token carries no content,
# only the fact that permitted data moved.
TOKEN_LENGTH = 32


# --------------------------------------------------------------- the token
def _digest(parts) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(repr(part).encode("utf-8"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()[:TOKEN_LENGTH]


def scope_token(store, tab_ids, *, include_unclassified: bool = False) -> str:
    """A stable token for the data a caller may read in `tab_ids`.

    The inputs are the row revisions, the trip revisions, the trip names and
    dates, and the active allocations. Nothing else is read, so two callers with
    different permissions get different tokens over the same database and one
    caller's token cannot be used to detect a change in data they may not see.

    `include_unclassified` is the owner-only 분류대기 bucket. A viewer is never
    given it, so the unclassified rows cannot move a viewer's token.
    """
    if store is None:
        return _digest(["no-store"])
    conn = store.conn
    tabs = sorted({str(t) for t in tab_ids if t})
    parts: list = ["v1"]
    for tab_id in tabs:
        trip = conn.execute(
            "SELECT tab_id, display_key, starts_on, ends_on, archived, deleted,"
            " revision FROM trip_tabs WHERE tab_id=?", (tab_id,)).fetchone()
        parts.append(("trip", trip))
        # `board_rows.payload_json` is deliberately not read. The row revision
        # already moves on every save, and reading the payload would put row
        # content into the digest of a screen that may not show it.
        for row in conn.execute(
                "SELECT row_id, revision FROM board_rows"
                " WHERE display_tab_id=? ORDER BY row_id", (tab_id,)):
            parts.append(("row", tab_id, row))
        for allocation in conn.execute(
                "SELECT allocation_id, source_row_id, amount_krw, active,"
                " source_revision, display_tab_id FROM income_allocations"
                " WHERE display_tab_id=? ORDER BY allocation_id", (tab_id,)):
            parts.append(("alloc", tab_id, allocation))
    if include_unclassified:
        for row in conn.execute(
                "SELECT row_id, revision FROM board_rows"
                " WHERE display_tab_id IS NULL ORDER BY row_id"):
            parts.append(("unclassified", row))
    return _digest(parts)


def owner_token(store, tab_id: str = "") -> str:
    """The token for the owner, over every trip plus 분류대기.

    The owner already sees the whole board, so the whole board is the scope. The
    currently open tab is included in the scope rather than narrowing it: the
    navigation rail shows a total for every trip, so a save in a trip the owner is
    not looking at still has to move the screen.
    """
    if store is None:
        return _digest(["no-store"])
    tab_ids = {t["tab_id"] for t in store.list_trips(include_archived=True)
               if not t.get("deleted")}
    if tab_id:
        tab_ids.add(tab_id)
    token = scope_token(store, tab_ids, include_unclassified=True)
    if tab_id == 'refunds':
        try:
            sources = store.conn.execute(
                "SELECT transaction_id, revision, transaction_direction, original_approval_number, "
                "amount_krw, duplicate_of, conflict_reason, parse_error FROM transactions ORDER BY transaction_id").fetchall()
        except Exception as exc:
            import sqlite3
            if not isinstance(exc, sqlite3.OperationalError) or 'no such table: transactions' not in str(exc):
                raise
            sources = []
        token = _digest([token, sources])
    return token


def viewer_token(store, tab_ids) -> str:
    """The token for a viewer, over the trips the access store allows.

    `tab_ids` comes from `AccessStore.visible_tabs`, so a revoked or expired
    assignment shrinks the scope instead of leaving a stale scope behind. No
    unclassified bucket is included and no other trip name is read.
    """
    return scope_token(store, tab_ids, include_unclassified=False)


def tokens_differ(presented: str, current: str) -> bool:
    """Compare two tokens without leaking anything about either.

    A missing or malformed presented token is "changed", so a page whose script
    could not read its own token re-renders once rather than sitting on a screen
    it cannot vouch for.
    """
    if not presented or not isinstance(presented, str):
        return True
    return presented != current


# ------------------------------------------------------- the browser script
# The client half. It is a separate script from the board's own, so the dirty
# guard and the polling loop are two readable pieces rather than one blob. They
# cooperate through the DOM only: this script asks "is an edit in progress?"
# by looking for the attributes the board script already sets, and it never
# writes one.
SCRIPT = """
(function(){
  var cfgEl=document.getElementById('live-config');
  if(!cfgEl||typeof fetch!=='function') return;
  var cfg;
  try{cfg=JSON.parse(cfgEl.textContent||'{}');}catch(e){return;}
  if(!cfg.state_url) return;

  var POLL=__POLL__, BACKOFF_MIN=__BACKOFF_MIN__, BACKOFF_MAX=__BACKOFF_MAX__;
  var token=cfg.token||'', pendingToken='', delay=POLL, timer=null, stopped=false;
  var statusEl=document.getElementById('live-status');
  // One request at a time. A poll in flight while a fragment fetch starts would
  // let the poll's older token land after the fragment's newer one, and the next
  // comparison would be against a token the screen was never rendered from.
  var busy=false;
  // A newer change that arrived while a fragment fetch was in flight. The token is
  // only committed once the DOM it describes is actually on screen, so a token
  // whose fragments failed to arrive is never treated as applied.
  var queuedToken='';

  function say(text,bad){
   if(!statusEl) return;
   statusEl.textContent=text||'';
   statusEl.className=bad?'meta live-err':'meta live-ok';
   statusEl.hidden=!text;
  }

  // The guard. Three things count as an edit in progress: a form the board
  // marked dirty, a save that has not come back yet, and the keyboard sitting in
  // a *text field* of an open panel. While one holds, a newer token is recorded
  // rather than applied.
  //
  // Focus only counts when it is in something the user can be typing into. A
  // button inside the panel keeps focus after it is clicked, and treating that as
  // an edit would block every refresh from the moment a save button is used,
  // which is the opposite of what was wanted.
  //
  // An open panel on its own is deliberately not a guard. The panel lives outside
  // every swappable region, so replacing the list cannot rewrite the form, and a
  // panel with nothing typed in it is not a draft to protect. If the open row was
  // saved elsewhere, the store still refuses this browser's save on
  // `expected_revision` and the typed value stays put, so nothing is lost by
  // letting the list move underneath.
  function isTextEntry(el){
   if(!el||!el.tagName) return false;
   var tag=el.tagName.toLowerCase();
   if(tag==='textarea') return !el.disabled;
   if(tag!=='input') return false;
   var type=(el.type||'text').toLowerCase();
   return !el.disabled&&['text','search','email','url','tel','password',
    'number','date','time','month','week'].indexOf(type)>=0;
  }
  function editInProgress(){
   if(document.querySelector('form[data-dirty="1"]')) return 'editing';
   if(document.querySelector('form[data-saving="1"]')) return 'saving';
   var el=document.activeElement;
   if(isTextEntry(el)&&el.form&&el.form.closest&&el.form.closest('.panel')){
    return 'focus';
   }
   return '';
  }

  // The board's own scroller is the `main` element, not the window: the app is
  // a full-height flex row and the ledger list scrolls inside it. Remembering
  // only the window offset would leave the scroll where the swap put it, which is
  // the one thing a refresh must not do. Both are kept, because a phone layout
  // scrolls the document instead.
  function scrollers(){
   var out=[];
   var main=document.getElementById('main');
   if(main&&main.scrollHeight>main.clientHeight) out.push(main);
   var nav=document.getElementById('nav');
   if(nav&&nav.scrollHeight>nav.clientHeight) out.push(nav);
   return out;
  }
  function remember(){
   var out={x:window.pageXOffset,y:window.pageYOffset,focus:null,caret:null,
    tops:[]};
   var list=scrollers();
   for(var i=0;i<list.length;i++){
    out.tops.push([list[i].id,list[i].scrollTop]);
   }
   var el=document.activeElement;
   if(el&&el.id){
    out.focus=el.id;
    if(el.selectionStart!==undefined&&el.selectionStart!==null){
     try{out.caret=[el.selectionStart,el.selectionEnd];}catch(e){}
    }
   }
   return out;
  }
  function restore(state){
   if(!state) return;
   for(var i=0;i<state.tops.length;i++){
    var box=document.getElementById(state.tops[i][0]);
    // The element is gone only if the swap removed the region itself, which the
    // fragments never do, so a missing id here means the page navigated and
    // there is nothing to restore onto.
    if(box) box.scrollTop=state.tops[i][1];
   }
   var el=state.focus?document.getElementById(state.focus):null;
   if(el&&el.focus){
    try{el.focus({preventScroll:true});}catch(e){try{el.focus();}catch(e2){}}
    if(state.caret&&el.setSelectionRange){
     try{el.setSelectionRange(state.caret[0],state.caret[1]);}catch(e){}
    }
   }
   if(window.scrollTo) window.scrollTo(state.x,state.y);
  }

  function replace(id,html){
   var slot=document.getElementById(id);
   if(!slot) return false;
   var holder=document.createElement('div');
   holder.innerHTML=html;
   var next=holder.firstElementChild;
   if(!next) return false;
   slot.parentNode.replaceChild(next,slot);
   return true;
  }

  // The regions that hold ledger data. A refusal clears them: if the session or
  // the permission is gone, the rows already on screen are no longer the caller's
  // to keep, and leaving them would be showing data the server has withdrawn.
  var PROTECTED=['live-nav','live-sum','live-rows','live-viewer','panel-slot'];

  function clearProtected(){
   for(var i=0;i<PROTECTED.length;i++){
    var el=document.getElementById(PROTECTED[i]);
    // Only the ledger regions are emptied. The chrome around them stays, so the
    // refusal is readable in place instead of the page going blank.
    if(el) el.innerHTML='';
   }
   var main=document.getElementById('main');
   if(main){
    var note=document.createElement('p');
    note.className='status err';
    note.setAttribute('role','alert');
    note.textContent='이 화면의 권한이 없어 장부 내용을 표시하지 않아요. '
     +'다시 로그인하거나 담당자를 문의해 주세요.';
    main.appendChild(note);
   }
  }

  // The one place a fragment is fetched, and the one place the token is
  // committed. Both are here so the two cannot come apart: the token moves only
  // after the markup it describes is on the screen.
  function drain(){
   // `busy` means a request of either kind is in flight. Starting a second would
   // let the older answer land last and leave the screen showing a state the next
   // comparison does not expect.
   if(stopped||busy||!pendingToken) return;
   if(editInProgress()){
    say('다른 화면에서 장부가 바뀌었어요. 저장하거나 닫으면 반영해요',false);
    return;
   }
    var want=pendingToken;
    busy=true;
   fetch(cfg.state_url,{credentials:'same-origin',cache:'no-store',
    headers:{'X-Part':'live-state'}})
    .then(function(r){
     if(r.status===401||r.status===403){
      stopped=true;
      clearProtected();
      say('로그인이 필요해요. 다시 로그인해 주세요',true);
      return null;
     }
     if(r.status===404){
      stopped=true;
      clearProtected();
      say('이 여행은 더 이상 열 수 없어요',true);
      return null;
     }
     if(!r.ok) throw new Error('status');
     return r.text();
    })
    .then(function(html){
     if(html===null) return;
     // The guard is asked again here, not only before the request. A draft can
     // start while the fragments are in flight, and swapping them in then would
     // replace the screen under a save that is about to be made from it. The
     // token is left uncommitted, so the next poll asks again.
     if(editInProgress()){
      say('다른 화면에서 장부가 바뀌었어요. 저장하거나 닫으면 반영해요',false);
      return;
     }
      // A fragment bundle is a sequence of <div id data-live> blocks. Each is
      // swapped in by name, so an absent block leaves that region alone.
      var holder=document.createElement('div');
      holder.innerHTML=html;
      var blocks=holder.querySelectorAll('[data-live]');
      // The viewport is read here, immediately before the swap, and not before the
      // fetch. Reading it before the fetch captured where the user was when the
      // request went out, and putting that back afterwards moved the screen to
      // where they had scrolled *to* while waiting. A fragment fetch can take
      // seconds, and scrolling during it is ordinary, so the value is only
      // meaningful at the moment the DOM actually changes.
      var state=remember();
      var applied=0;
      for(var i=0;i<blocks.length;i++){
       if(replace(blocks[i].getAttribute('data-live'),blocks[i].outerHTML)){
        applied++;
       }
      }
      if(!applied){
       // Nothing was replaced, so the screen does not show this token. Committing
       // it would make the next poll report "no change" over a stale screen.
       say('반영하지 못했어요. 곧 다시 확인해요',true);
       return;
      }
      // Restored only here: after a swap that happened, and not after a deferred
      // draft, a failed fetch or a refusal. Putting a remembered position back on a
      // screen that was not touched is a move the user did not ask for.
      restore(state);
     // Commit only now: the DOM and the token move together.
     token=want;
     pendingToken=(queuedToken&&queuedToken!==want)?queuedToken:'';
     queuedToken='';
     if(!pendingToken) say('',false);
    })
     .catch(function(){
      // A fragment fetch that failed is a transport failure, exactly as a failed
      // poll is. It backs off and stays inside a bound, and the token is left
      // uncommitted so the change is still outstanding. Retrying it straight away
      // would be a tight loop against a server that is already in trouble.
      delay=Math.min(Math.max(delay*2,BACKOFF_MIN),BACKOFF_MAX);
      say('반영하지 못했어요. 곧 다시 확인해요',true);
     })
      .then(function(){
       // No `restore` here. The only path that moves the screen back is the one
       // that replaced something, and it has already done it. A deferred draft, a
       // failed fetch and a refusal all end up here, and none of them touched the
       // DOM, so restoring here would move the user's scroll and focus for a
       // screen that had not changed.
       busy=false;
       if(pendingToken&&!stopped){
        // A change that landed mid-fetch, or one whose fetch just failed, waits
        // for the next scheduled pass rather than being retried in this one.
        schedule(delay);
       }
      });
  }

  function check(){
   if(stopped) return;
   // A background tab is not asked anything. The moment it is shown again the
   // pending change is picked up, so nothing is missed by not looking.
   if(document.hidden){schedule(POLL);return;}
   // A fragment fetch is already applying a change. Asking again now would put a
   // second poll and a second fragment fetch in flight, and the older of the two
   // could land last. The fragment's own completion schedules the next check.
   if(busy){return;}
   var url=cfg.state_url+(cfg.state_url.indexOf('?')>=0?'&':'?')+'token='+
    encodeURIComponent(token);
   busy=true;
   fetch(url,{credentials:'same-origin',cache:'no-store'})
    .then(function(r){
     if(r.status===401||r.status===403||r.status===404){
      // The server refused on the session or on the trip. That is the existing
      // failure path, not a transport problem, so retrying would only repeat
      // it: stop, and take the ledger off the screen, because what is on it is no
      // longer this caller's to read.
      stopped=true;
      clearProtected();
      say(r.status===404
        ?'이 여행은 더 이상 열 수 없어요'
        :'로그인이 필요해요. 다시 로그인해 주세요',true);
      return null;
     }
     if(!r.ok) throw new Error('status');
     return r.json();
    })
     .then(function(data){
      if(!data) return;
      // A poll that came back at all is a working connection, so the backoff is
      // released here and nowhere else. A page that was refusing is stopped
      // before this point, so this cannot revive one.
      delay=POLL;
      if(!data.changed) return;
     if(pendingToken&&pendingToken!==data.token){
      // A change already waiting to be applied is newer than this answer. The
      // waiting one wins, so the screen never steps backwards to a state it has
      // already passed.
      queuedToken=data.token;
      return;
     }
     pendingToken=data.token;
    })
    .catch(function(){
     // Transport failure only. The user is told, and the wait grows but stays
     // inside a bound so a restored connection is noticed.
     delay=Math.min(Math.max(delay*2,BACKOFF_MIN),BACKOFF_MAX);
     say('연결이 불안정해요. 다시 확인하는 중이에요',true);
    })
     .then(function(){
      busy=false;
      // `drain` puts a polled change on the screen, on the same pass that found
      // it. If an edit is in progress it holds the token instead, and the
      // `ledger:saved` event below is what brings it back.
      drain();
      // The next poll is always armed here, and re-armed from the timer as well.
      // Arming in both places is deliberate: `drain` may have started a fragment
      // fetch, and arming only from the timer would leave a window in which no
      // timer exists, so a change arriving in that window would wait for a poll
      // that nothing had scheduled.
      schedule(delay);
     });
  }

  function schedule(ms){
   if(stopped) return;
   if(timer) clearTimeout(timer);
   timer=setTimeout(function(){
    timer=null;
    check();
    // `check` declines while a request is in flight, so nothing armed the next
    // one. Re-arm here, or the loop stops for good after the first overlap.
    if(!timer&&!stopped&&!busy) schedule(delay);
   },ms);
  }

  // Coming back to the tab asks immediately rather than waiting out the timer.
  document.addEventListener('visibilitychange',function(){
   if(!document.hidden){if(timer) clearTimeout(timer);timer=null;check();}
  });
  window.addEventListener('online',function(){
   if(timer) clearTimeout(timer);timer=null;check();});
  // A save that has just finished is the moment a deferred change is wanted. The
  // pending token is already there; this only releases the guard. The backoff is
  // deliberately not reset here: this event is not a sign the connection works,
  // and resetting the delay on it would make a page that has been failing quietly
  // start polling at the fast interval again.
  window.addEventListener('ledger:saved',function(){drain();});

  if(cfg.token){
   // The screen was rendered from this token. Ask once straight away so a change
   // made in the seconds before the page loaded is not a full interval late.
   check();
  }else{
   drain();
  }
  window.__ledgerLiveSync={check:check,drain:drain,applyPending:drain,
   token:function(){return token;},pendingToken:function(){return pendingToken;},
   isStopped:function(){return stopped;},delay:function(){return delay;},
   isBusy:function(){return busy;},
   regionCount:function(id){return document.querySelectorAll('#'+id).length;}};
})();
"""

SCRIPT = (SCRIPT
          .replace("__POLL__", str(POLL_INTERVAL_MS))
          .replace("__BACKOFF_MIN__", str(BACKOFF_START_MS))
          .replace("__BACKOFF_MAX__", str(BACKOFF_CEILING_MS)))


# --------------------------------------------------------- page fragments
def state_url(tab: str = "", query: str = "", kind: str = "", archived: str = "",
              selected: str = "") -> str:
    """The URL the browser polls, carrying the same view state as the screen.

    The archived drawer and the open row are part of the view state, not extras.
    A refresh that dropped them would close the drawer the user opened and lose
    which row the panel belongs to, so a refreshed rail would come back closed and
    a refreshed row list would come back with nothing selected.
    """
    from urllib.parse import urlencode

    params = {"tab": tab or ""}
    if query:
        params["q"] = query
    if kind:
        params["kind"] = kind
    if archived:
        params["arch"] = archived
    if selected:
        params["row"] = selected
    return "/api/live/state?" + urlencode(params)


def client_config(token: str, tab: str = "", query: str = "", kind: str = "",
                  role: str = "owner", archived: str = "",
                  selected: str = "") -> str:
    """The JSON the browser script reads, as a safe script element body.

    A `<script type=application/json>` block is used rather than a data attribute
    so the value is escaped as JSON text and never parsed as markup.
    """
    payload = {"state_url": state_url(tab, query, kind, archived, selected),
               "token": token or "", "role": role}
    body = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return (f"<script type='application/json' id='live-config'>{body}</script>")


def _block(name: str, inner: str) -> str:
    """One swappable region of a fragment bundle.

    The region carries its name as an `id` and repeats it in `data-live`. The
    `id` is what the browser swaps by and what the rendered page already uses, so
    the region keeps its identity across the swap; `data-live` is what the
    browser finds the regions *in* a fetched bundle, where there is no id to
    look up yet. A bundle written with only `data-live` would be swapped in and
    then be unfindable by name, which is a refresh that works once and never
    again.
    """
    return (f"<div id='{name}' data-live='{name}'>{inner}</div>")


def owner_fragments(store, tab: str, query: str, kind: str, selected: str,
                    archived: str) -> str:
    """The owner page regions, re-rendered for a live refresh.

    Three regions and no more: the navigation rail, the totals, and the two row
    lists. The edit panel is deliberately not among them, because replacing a
    panel is what would destroy a draft.
    """
    from . import ledger_design

    parts = [_block("live-nav", ledger_design.nav_part(tab, query, kind, archived)),
             _block("live-sum", ledger_design.summary_part(tab, kind, query)),
             _block("live-rows", ledger_design.rows_part(tab, query, kind,
                                                        selected, archived))]
    return "".join(parts)


def viewer_fragments(session, access, ledger_store, tab: str = "") -> str:
    """The viewer page region: the viewer's own trips and their totals.

    `access` answers which trips this viewer may read and `ledger_store` holds
    the trips and rows. Built from the viewer allowlist on the server, the same
    way the page itself is. No other trip name and no internal memo is in this
    fragment, so putting it on the wire cannot widen what a viewer may read.
    """
    from . import ledger_design

    allowed = access.visible_tabs(session.user_id)
    trips = []
    for trip in (ledger_store.list_trips(include_archived=True)
                 if ledger_store is not None else []):
        if trip["tab_id"] not in allowed:
            continue
        rows = (ledger_store.list_tab_rows(trip["tab_id"])
                if ledger_store is not None else [])
        income = sum(r["amount_krw"] for r in rows if r["row_kind"] == "income")
        expense = sum(r["amount_krw"] for r in rows if r["row_kind"] != "income")
        trips.append({"tab_id": trip["tab_id"],
                      "display_key": trip["display_key"],
                      "starts_on": trip["starts_on"],
                      "ends_on": trip["ends_on"],
                      "income_krw": income, "expense_krw": expense,
                      "balance_krw": income - expense, "row_count": len(rows)})
    return _block("live-viewer", ledger_design.viewer_trips_html(trips))
