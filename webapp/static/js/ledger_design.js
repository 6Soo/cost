
(function(){
 document.addEventListener('DOMContentLoaded',function(){
  var root=document.getElementById('participant-trip-panel');
  if(!root)return;
  var dlg=null,pending=null,form=null,busy=false;
  function ask(message,submit){
   if(!dlg){if(window.confirm(message))submit();return;}
   dlg.querySelector('p').textContent=message;pending=submit;dlg.showModal();
  }
  function write(target){
   if(busy)return;
   busy=true;
   var status=root.querySelector('.participant-write-status');
   if(status)status.textContent='저장 중입니다.';
   fetch(target.action,{method:'POST',credentials:'same-origin',
    headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams(new FormData(target)).toString()})
    .then(function(r){return r.json().then(function(body){if(!r.ok)throw new Error(body.code==='STALE_INPUT'?'자료가 변경되었습니다. 새로고침 후 확인해 주세요.':'연결을 저장하지 못했습니다. 새로고침 후 확인해 주세요.');return body;});})
    .then(function(){location.reload();})
    .catch(function(error){busy=false;if(status)status.textContent=error.message;});
  }
  function bindPanel(){
   dlg=root.querySelector('#participant-link-confirm');
   form=root.querySelector('.participant-keyboard-link');
   if(dlg)dlg.addEventListener('close',function(){var action=pending;pending=null;if(dlg.returnValue==='confirm'&&action)action();});
   root.querySelectorAll('.participant-income-status').forEach(function(template){
    var cell=document.querySelector('.participant-insurance-cell[data-income-ref="'+CSS.escape(template.dataset.incomeRef)+'"]');
    if(!cell)return;
    var button=cell.querySelector('.participant-row-connect');
    cell.replaceChildren(template.content.cloneNode(true));if(button)cell.appendChild(button);
   });
   root.querySelectorAll('.participant-cards li[draggable=true]').forEach(function(card){
    card.addEventListener('dragstart',function(e){root.dataset.dragParticipant=card.dataset.participant;e.dataTransfer.clearData();e.dataTransfer.effectAllowed='link';});
    card.addEventListener('dragend',function(){delete root.dataset.dragParticipant;});
   });
  }
  function choose(cell,id){
   if(!form)return;
   form.hidden=false;form.querySelector('[name=income_ref]').value=cell.dataset.incomeRef;
   if(id)form.querySelector('[name=participant_id]').value=id;
   form.scrollIntoView({block:'nearest'});
   form.querySelector('[name=participant_id]').focus();
  }
  document.addEventListener('submit',function(e){
   var target=e.target;
   if(!target.matches('form[action="/api/participants/link"],form[action="/api/participants/unlink"]') ||
      !(root.contains(target)||target.closest('.participant-insurance-cell')))return;
   e.preventDefault();
   if(busy)return;
   var person=target.querySelector('[name=participant_id]');
   var label=person.tagName==='SELECT'?(person.selectedOptions[0]||{}).textContent:'';
   if(!person.value)return;
   ask(target.action.endsWith('/unlink')?'이 참가자 연결을 해제할까요?':'이 수입 기록을 '+(label||'선택한')+' 보험 참가자와 연결할까요?',function(){write(target);});
  });
  document.addEventListener('click',function(e){
   var button=e.target.closest('.participant-row-connect');if(!button)return;
   var cell=button.closest('.participant-insurance-cell');
   if(form){choose(cell);return;}
   root.open=true;loadPanel().then(function(){choose(cell);});
  });
  document.addEventListener('dragover',function(e){var cell=e.target.closest('.participant-insurance-cell');if(cell&&root.dataset.dragParticipant){e.preventDefault();cell.classList.add('participant-drop-target');}});
  document.addEventListener('dragleave',function(e){var cell=e.target.closest('.participant-insurance-cell');if(cell)cell.classList.remove('participant-drop-target');});
  document.addEventListener('drop',function(e){
   var cell=e.target.closest('.participant-insurance-cell');if(!cell)return;
   e.preventDefault();cell.classList.remove('participant-drop-target');
   var id=root.dataset.dragParticipant;delete root.dataset.dragParticipant;
   if(!id||!form)return;choose(cell,id);form.requestSubmit();
  });
  var loading=null;
  function loadPanel(){
   if(root.dataset.loaded==='1')return Promise.resolve();
   if(loading)return loading;
   var q=new URLSearchParams({trip:root.dataset.trip||''}),current=new URLSearchParams(location.search);
   ['participant_q','participant_offset','participant_income_offset'].forEach(function(key){if(current.has(key))q.set(key,current.get(key));});
   loading=fetch('/api/participants/trip-panel?'+q.toString(),{headers:{'Accept':'text/html'},credentials:'same-origin'})
    .then(function(r){if(!r.ok)throw new Error();return r.text();})
    .then(function(markup){var doc=new DOMParser().parseFromString(markup,'text/html');var fresh=doc.querySelector('#participant-trip-panel');if(!fresh)throw new Error();root.innerHTML=fresh.innerHTML;root.dataset.loaded='1';bindPanel();})
    .catch(function(){var content=root.querySelector('[data-participant-content]');if(content)content.textContent='참가자 정보를 불러오지 못했습니다. 다시 열어 주세요.';})
    .finally(function(){loading=null;});return loading;
  }
  root.addEventListener('toggle',function(){if(root.open)loadPanel();});
 });
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

  // Trip tab expense copy button (contract: Google 7-column B:H TSV copy)
  document.addEventListener('click',async function(e){
   var btn=e.target.closest&&e.target.closest('#copy-trip-expenses,[data-copy-trip-tsv]');
   if(!btn||btn.disabled) return;
   var tab=btn.getAttribute('data-tab');
   if(!tab) return;
   var wrap=btn.closest('.trip-copy-wrap')||btn.parentNode;
   var status=wrap&&wrap.querySelector('.copy-status');
   btn.disabled=true;
   try{
    if(status){
     status.textContent='복사 중...';
     status.className='copy-status loading';
    }
    var filters=new URLSearchParams(location.search);
    var params=new URLSearchParams();
    ['q','kind'].forEach(function(key){if(filters.has(key)) params.set(key,filters.get(key));});
    var res=await fetch('/api/tabs/'+encodeURIComponent(tab)+'/tsv?'+params.toString());
    if(!res.ok){
     var errJson=await res.json().catch(function(){return {};});
     throw new Error(errJson.message||('복사 요청 실패 ('+res.status+')'));
    }
    var data=await res.json();
    if(!data.tsv||data.row_count===0){
     if(status){
      status.textContent=data.held&&data.held.length?'복사 가능한 지출이 없습니다. '+data.held.length+'건의 날짜·금액·증빙을 확인해 주세요.':'지출 내역이 없습니다.';
      status.className='copy-status';
     }
     return;
    }
    var textToCopy=data.tsv;
    if(navigator.clipboard&&navigator.clipboard.writeText){
     await navigator.clipboard.writeText(textToCopy);
    }else{
     var ta=document.createElement('textarea');
     ta.value=textToCopy;
     ta.style.position='fixed';
     ta.style.opacity='0';
     document.body.appendChild(ta);
     ta.select();
     try{if(!document.execCommand('copy')) throw new Error('클립보드 복사가 허용되지 않았습니다.');}
     finally{document.body.removeChild(ta);}
    }
    try{
     localStorage.setItem('gcopy-trip:'+tab,new Date().toLocaleString('ko-KR'));
    }catch(err){}
    if(status){
     var countStr=data.row_count+'건';
     var sumStr=data.total_krw?(' · '+Number(data.total_krw).toLocaleString('ko-KR')+'원'):'';
     status.textContent='지출내용이 복사되었습니다! ('+countStr+sumStr+') Google 시트에 붙여넣으세요.'+(data.held&&data.held.length?' 제외 '+data.held.length+'건: 날짜·금액·증빙 확인 필요':'');
     status.className='copy-status success';
    }
   }catch(err){
    if(status){
     status.textContent='복사 실패: '+(err.message||'클립보드 접근 오류');
     status.className='copy-status err';
    }
   }finally{
    btn.disabled=false;
    setTimeout(function(){
     if(status&&status.classList.contains('success')){
      status.textContent='';
      status.className='copy-status';
     }
    },5000);
   }
  });
 })();
