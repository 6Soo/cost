
(function(){
 document.addEventListener('DOMContentLoaded',function(){
  var tripMore=document.getElementById('trip-settings');
  if(tripMore){
   var tripMoreSummary=tripMore.querySelector('summary');
   var syncTripMore=function(){if(tripMoreSummary)tripMoreSummary.setAttribute('aria-expanded',String(tripMore.open));};
   tripMore.addEventListener('toggle',syncTripMore);
   syncTripMore();
   tripMore.addEventListener('keydown',function(e){if(e.key==='Escape'&&tripMore.open){e.preventDefault();tripMore.open=false;if(tripMoreSummary)tripMoreSummary.focus();}});
  }
  if(!document.querySelector('.trip-actions'))return;
  document.documentElement.classList.add('trip-actions-ready');
  function sync(){
   document.querySelectorAll('.trip-actions [data-trip-panel]').forEach(function(button){
    var panel=document.getElementById(button.dataset.tripPanel);
    button.setAttribute('aria-expanded',String(!!panel&&panel.open));
   });
  }
  document.addEventListener('click',function(event){
   var button=event.target.closest('[data-trip-panel]');
   if(!button)return;
   var panel=document.getElementById(button.dataset.tripPanel);
   if(!panel)return;
   event.preventDefault();
   var opening=!panel.open;
   document.querySelectorAll('#participant-trip-panel,#trip-review-panel').forEach(function(other){other.open=false;});
   panel.open=opening;sync();
   if(opening&&!button.closest('.trip-actions')){
    var target=panel.querySelector('a,button,input');
    if(target)target.focus();
    panel.scrollIntoView({block:'nearest'});
   }
  });
  document.addEventListener('toggle',sync,true);
  document.addEventListener('keydown',function(event){
   if(event.key===' '&&event.target.matches('.trip-actions [data-trip-panel]')){
    event.preventDefault();event.target.click();
   }
  });
  var region=document.getElementById('live-rows');
  if(region)new MutationObserver(function(){
   var button=document.querySelector('.trip-actions [data-trip-panel="trip-review-panel"]');
   var panel=document.getElementById('trip-review-panel');
   if(button&&panel)panel.open=button.getAttribute('aria-expanded')==='true';
   sync();
  }).observe(region,{childList:true});
  sync();
 });
})();

/* PR-4 ledger workspace: APG tabs, grouped expense rows, and native drawer. */
(function(){
  function drawer(){return document.getElementById('ledger-drawer');}
  function rowSelector(){return '.tw tr[data-id],.lst .list-row[data-id]';}
  function closeDrawer(){
    document.dispatchEvent(new Event('ledger:close-panel'));
  }
  function showDrawer(row,range){
    document.dispatchEvent(new CustomEvent('ledger:open-row',{detail:{id:row.dataset.id,row:row,range:range}}));
  }
  function activateTab(button,focus){
    var root=button.closest('.view-tabs');if(!root)return;
    var buttons=Array.from(root.querySelectorAll('[role=tab]'));
    buttons.forEach(function(item){
      var active=item===button;item.setAttribute('aria-selected',active?'true':'false');item.tabIndex=active?0:-1;
      var panel=document.getElementById(item.getAttribute('aria-controls'));if(panel)panel.hidden=!active;
      if(!item.id)item.id='tab-'+item.getAttribute('aria-controls');
      if(panel)panel.setAttribute('aria-labelledby',item.id);
    });
    if(focus)button.focus();
  }
  function tabForHash(hash){
    var map={'#trip-income':'view-income','#participant-trip-panel':'view-participants','#trip-reservations':'view-reservations','#trip-expense-copy':'view-expense','#copy-trip-expenses':'view-expense'};
    return map[hash]||((hash||'').replace(/^#/,'').indexOf('view-')===0?(hash||'').slice(1):'');
  }
  function restoreHash(){
    var id=tabForHash(location.hash);if(!id)return;
    var button=document.querySelector('[role=tab][aria-controls="'+CSS.escape(id)+'"]');if(button){activateTab(button,false);var target=document.getElementById(id);if(target)setTimeout(function(){var anchor=target.querySelector(location.hash);(anchor||target).scrollIntoView({block:'start'});},0);}
  }
  var grouping=false;
  function groupExpenses(){
    if(grouping)return;
    grouping=true;
    try{
    var toggle=document.querySelector('[data-group-expenses]');if(!toggle)return;
    document.querySelectorAll('.lst').forEach(function(list){
      list.querySelectorAll('.expense-category-group').forEach(function(head){head.remove();});
      var mobileRows=Array.from(list.querySelectorAll(':scope > li[data-kind=expense]'));
      mobileRows.forEach(function(row,index){if(row.dataset.ledgerOrder===undefined)row.dataset.ledgerOrder=String(index);});
      mobileRows.sort(function(a,b){return Number(a.dataset.ledgerOrder)-Number(b.dataset.ledgerOrder);});
      if(!toggle.checked){mobileRows.forEach(function(row){list.appendChild(row);});return;}
      var mobileGroups=new Map();
      mobileRows.forEach(function(row){var key=row.dataset.category||'기타';if(!mobileGroups.has(key))mobileGroups.set(key,[]);mobileGroups.get(key).push(row);});
      mobileGroups.forEach(function(rows,key){
        var head=document.createElement('li');head.className='list-group expense-category-group';
        var label=document.createElement('span');label.textContent=key+' · '+rows.length+'건';head.appendChild(label);
        var total=document.createElement('span');total.className='tnum';
        total.textContent=new Intl.NumberFormat('ko-KR').format(rows.reduce(function(sum,row){return sum+Number(row.dataset.amount||0);},0))+'원';head.appendChild(total);
        list.appendChild(head);rows.forEach(function(row){list.appendChild(row);});
      });
    });
    var table=document.getElementById('tbl');if(!table)return;
    var body=table.querySelector('tbody.expense-rows[data-kind=expense]');if(!body)return;
    body.querySelectorAll('.group-row').forEach(function(row){row.remove();});
    var rows=Array.from(body.querySelectorAll(':scope > tr[data-id]'));
    var entries=rows.map(function(row,index){
      if(row.dataset.ledgerOrder===undefined)row.dataset.ledgerOrder=String(index);
      return {row:row,move:body.querySelector('[data-move-for="'+CSS.escape(row.dataset.id)+'"]')};
    });
    // Detach the data rows and their optional move forms before rebuilding the
    // body. Otherwise new group headers would be appended after the original
    // rows and the grouping toggle would appear to do nothing.
    entries.forEach(function(entry){
      entry.row.remove();
      if(entry.move)entry.move.remove();
    });
    if(!toggle.checked){
      entries.sort(function(a,b){return Number(a.row.dataset.ledgerOrder)-Number(b.row.dataset.ledgerOrder);});
      entries.forEach(function(entry){body.appendChild(entry.row);if(entry.move)body.appendChild(entry.move);});
      return;
    }
    var groups=new Map();entries.forEach(function(entry){var key=entry.row.dataset.category||'기타';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(entry);});
    groups.forEach(function(items,key){
      items.sort(function(a,b){return Number(a.row.dataset.ledgerOrder)-Number(b.row.dataset.ledgerOrder);});
      var total=items.reduce(function(sum,entry){return sum+Number(entry.row.dataset.amount||0);},0);
      var head=document.createElement('tr');head.className='group-row';
      var cell=document.createElement('th');cell.scope='rowgroup';cell.colSpan=table.querySelectorAll('thead th').length;cell.textContent=key+' · '+items.length+'건';
      var totalSpan=document.createElement('span');totalSpan.className='group-total';totalSpan.textContent=new Intl.NumberFormat('ko-KR').format(total)+'원';cell.appendChild(totalSpan);head.appendChild(cell);body.appendChild(head);
      items.forEach(function(entry){body.appendChild(entry.row);if(entry.move)body.appendChild(entry.move);});
    });
    }finally{grouping=false;}
  }
  document.addEventListener('click',function(event){
    var target=event.target;
    var tabButton=target.closest&&target.closest('[role=tab]');
    if(tabButton){event.preventDefault();event.stopImmediatePropagation();activateTab(tabButton,false);return;}
    var tripOpen=target.closest&&target.closest('#trip-switch-open');
    if(tripOpen){event.preventDefault();var d=document.getElementById('trip-switch-dialog');if(d)d.showModal();return;}
    if(target.closest&&target.closest('[data-trip-switch-close]')){var d=document.getElementById('trip-switch-dialog');if(d)d.close();return;}
    if(target.closest&&target.closest('[data-drawer-close],#drawer-close,#p-close,#p-cancel')){event.preventDefault();event.stopImmediatePropagation();closeDrawer();return;}
    var row=target.closest&&target.closest(rowSelector());
    if(row&&!target.closest('form,select,input,textarea,a:not(.lr-hit)')){event.preventDefault();event.stopImmediatePropagation();showDrawer(row,event.shiftKey);return;}
  },true);
  document.addEventListener('keydown',function(event){
    if(event.key==='Escape'&&drawer()&&drawer().open){event.preventDefault();event.stopImmediatePropagation();closeDrawer();return;}
    if((event.key==='Enter'||event.key===' '||event.key==='Spacebar')){
      var row=event.target.closest&&event.target.closest(rowSelector());
      if(row&&!event.target.closest('button,select,input,textarea,a')){
        event.preventDefault();event.stopImmediatePropagation();showDrawer(row,event.shiftKey);return;
      }
    }
    var tab=event.target.closest&&event.target.closest('[role=tab]');if(!tab)return;
    var tabs=Array.from(tab.closest('[role=tablist]').querySelectorAll('[role=tab]')),index=tabs.indexOf(tab),next=index;
    if(event.key==='ArrowRight')next=(index+1)%tabs.length;else if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=tabs.length-1;else return;
    event.preventDefault();event.stopImmediatePropagation();activateTab(tabs[next],true);
  },true);
  document.addEventListener('DOMContentLoaded',function(){
    var dialog=drawer(),panel=dialog&&dialog.querySelector('#panel');if(dialog&&panel&&!dialog.open)dialog.showModal();
    var close=dialog&&dialog.querySelector('[data-drawer-close]');if(close)close.addEventListener('click',closeDrawer);
    var switcher=document.getElementById('trip-switch-dialog'),search=document.getElementById('trip-switch-search');
    if(switcher) switcher.addEventListener('close',function(){if(search)search.value='';});
    if(search)search.addEventListener('input',function(){var q=search.value.trim().toLocaleLowerCase();document.querySelectorAll('[data-trip-switch-item]').forEach(function(item){item.parentElement.hidden=!!q&&!item.textContent.toLocaleLowerCase().includes(q);});});
    var tabs=document.querySelectorAll('[role=tab]');tabs.forEach(function(tab,index){tab.id=tab.id||'tab-'+tab.getAttribute('aria-controls');tab.tabIndex=tab.getAttribute('aria-selected')==='true'?0:-1;var panel=document.getElementById(tab.getAttribute('aria-controls'));if(panel)panel.setAttribute('aria-labelledby',tab.id);if(index===0&&!tab.hasAttribute('aria-selected'))activateTab(tab,false);});
    restoreHash();window.addEventListener('hashchange',restoreHash);
    var toggle=document.querySelector('[data-group-expenses]');if(toggle){try{toggle.checked=localStorage.getItem('cost-board-group')==='1';}catch(error){};toggle.addEventListener('change',function(){try{localStorage.setItem('cost-board-group',toggle.checked?'1':'0');}catch(error){};groupExpenses();});groupExpenses();}
    var live=document.getElementById('live-rows');
    if(live&&window.MutationObserver)new MutationObserver(function(mutations){
      if(grouping)return;
      var replaced=mutations.some(function(m){return Array.from(m.addedNodes||[]).some(function(node){return node.id==='tbl'||node.querySelector&&node.querySelector('#tbl');});});
      if(replaced)groupExpenses();
    }).observe(live,{childList:true,subtree:true});
  });
})();
(function(){
 document.addEventListener('click',async function(event){
  var button=event.target.closest('[data-google-sync]');
  if(!button||button.disabled)return;
  var scope=button.closest('.trip-copy-wrap,.income-sync')||document;
  var status=scope.querySelector('[data-google-sync-status]');
  var token=document.querySelector('input[name="csrf"]');
  button.disabled=true;button.setAttribute('aria-busy','true');
  if(status)status.textContent='Google 장부를 읽고 있습니다…';
  try{
   var response=await fetch('/api/google-ledger/sync',{method:'POST',credentials:'same-origin',
    headers:{'X-CSRF-Token':button.getAttribute('data-csrf')||(token?token.value:'')},body:'{}'});
   if(!response.ok)throw new Error('동기화를 시작하지 못했습니다. 화면을 새로 연 뒤 다시 눌러 주세요.');
   var result=await response.json(),deadline=Date.now()+180000;
   while(result.status==='running'&&Date.now()<deadline){
    await new Promise(function(resolve){setTimeout(resolve,1000);});
    response=await fetch('/api/google-ledger/sync',{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error('동기화 결과를 확인하지 못했습니다. 다시 눌러 주세요.');
    result=await response.json();
   }
   if(result.status==='done'){location.reload();return;}
   throw new Error(result.status==='running'?'동기화가 계속 진행 중입니다. 잠시 후 다시 확인해 주세요.':result.message||'동기화하지 못했습니다. 다시 눌러 주세요.');
  }catch(error){if(status)status.textContent=error.message;}
  finally{button.disabled=false;button.removeAttribute('aria-busy');}
 });
 document.addEventListener('DOMContentLoaded',function(){
  var root=document.getElementById('participant-trip-panel');
  if(!root)return;
  var dlg=null,pending=null,form=null,busy=false,connectSequence=0;
  function closeCandidates(row,restoreFocus){
   if(!row)return;
   var button=row.dataset.connectIncomeRef!==undefined
    ?document.querySelector('.participant-insurance-cell[data-income-ref="'+CSS.escape(row.dataset.connectIncomeRef)+'"] button')
    :document.querySelector('button[data-insurance-evidence="'+CSS.escape(row.dataset.insuranceRowEvidence)+'"]');
   row.remove();
   if(button){button.setAttribute('aria-expanded','false');if(restoreFocus)button.focus({preventScroll:true});}
  }
  document.addEventListener('keydown',function(e){
   if(e.key!=='Escape')return;
   var row=e.target.closest('.insurance-candidate-row');
   if(!row&&e.target.matches('[data-insurance-evidence],[data-connect-income]'))row=document.getElementById(e.target.getAttribute('aria-controls'));
   if(row){e.preventDefault();closeCandidates(row,true);}
  });
  function ask(message,submit){
   if(!dlg){if(window.confirm(message))submit();return;}
   root.open=true;
   dlg.querySelector('p').textContent=message;pending=submit;
   document.body.appendChild(dlg);dlg.showModal();
  }
  function write(target){
   if(busy)return;
   busy=true;
   var choices=target.querySelectorAll('[data-pick-participant]');
   choices.forEach(function(button){button.disabled=true;});
   var status=target.closest('.insurance-candidate-row')?.querySelector('.participant-inline-status')||root.querySelector('.participant-write-status');
   if(status)status.textContent='저장 중입니다.';
   fetch(target.action,{method:'POST',credentials:'same-origin',
    headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams(new FormData(target)).toString()})
    .then(function(r){return r.json().then(function(body){if(!r.ok)throw new Error(body.code==='STALE_INPUT'?'자료가 변경되었습니다. 새로고침 후 확인해 주세요.':'연결을 저장하지 못했습니다. 새로고침 후 확인해 주세요.');return body;});})
    .then(function(){location.reload();})
    .catch(function(error){busy=false;choices.forEach(function(button){button.disabled=false;});if(status)status.textContent=error.message;});
  }
  function bindPanel(){
   dlg=root.querySelector('#participant-link-confirm');
   form=root.querySelector('.participant-keyboard-link');
   if(dlg){var dialogParent=dlg.parentNode;dlg.addEventListener('close',function(){var action=pending;pending=null;dialogParent.appendChild(dlg);if(dlg.returnValue==='confirm'&&action)action();});}
   root.querySelectorAll('.participant-income-status').forEach(function(template){
    var cell=document.querySelector('.participant-insurance-cell[data-income-ref="'+CSS.escape(template.dataset.incomeRef)+'"]');
    if(!cell||cell.dataset.incomeRefundComplete==='1')return;
    var incomeTable=cell.closest('#income-tbl');
    if(incomeTable&&template.hasAttribute('data-google-generation')&&
       incomeTable.dataset.googleGeneration!==template.dataset.googleGeneration){
     cell.textContent='자료 변경 · 새로고침 필요';return;
    }
    var content=document.createElement('div');content.className='participant-cell-content';
    content.appendChild(template.content.cloneNode(true));
    cell.replaceChildren(content);
   });
   root.querySelectorAll('.participant-cards li[draggable=true]').forEach(function(card){
    card.addEventListener('dragstart',function(e){root.dataset.dragParticipant=card.dataset.participant;e.dataTransfer.clearData();e.dataTransfer.effectAllowed='link';});
    card.addEventListener('dragend',function(){delete root.dataset.dragParticipant;});
   });
  }
  function choose(cell,id,toggle){
   var button=cell.querySelector('[data-connect-income],[data-insurance-evidence]');
   var existing=Array.from(document.querySelectorAll('.insurance-candidate-row[data-connect-income-ref]')).find(function(row){return row.dataset.connectIncomeRef===cell.dataset.incomeRef;});
   if(existing){if(toggle){closeCandidates(existing,false);return;}closeCandidates(existing,false);}
   var sourceRow=cell.closest('tr');
   if(!sourceRow)return;
   var row=document.createElement('tr');row.className='insurance-candidate-row';
   row.dataset.connectIncomeRef=cell.dataset.incomeRef;
   row.id='income-connect-'+(++connectSequence);
   var detail=document.createElement('td');
   detail.colSpan=Array.from(sourceRow.cells).reduce(function(total,item){return total+item.colSpan;},0);
   var content=document.createElement('div');content.className='insurance-candidate-content';
   detail.appendChild(content);row.appendChild(detail);sourceRow.after(row);
   if(button){button.setAttribute('aria-controls',row.id);button.setAttribute('aria-expanded','true');}
   var reason=cell.querySelector('.participant-match-reason');
   if(reason){var explanation=document.createElement('p');explanation.textContent=reason.textContent+'입니다. 가림 이름만으로 구별할 수 없어 직접 연결이 필요합니다.';content.appendChild(explanation);}
   var notice=root.querySelector('.participant-connect-notice');
   if(!form){
    var empty=document.createElement('p');empty.tabIndex=-1;empty.textContent='연결할 보험 참가자가 없습니다. 이 여행의 보험가입내역과 수입 자료를 확인해 주세요.';content.appendChild(empty);empty.focus();return;
   }
   var localForm=form.cloneNode(true);localForm.hidden=false;content.appendChild(localForm);
   var localStatus=document.createElement('p');localStatus.className='participant-inline-status';localStatus.setAttribute('role','status');content.appendChild(localStatus);
   var income=localForm.querySelector('[name=income_ref]');
   income.value=cell.dataset.incomeRef;
   if(!income.value){
    if(notice){notice.hidden=false;notice.textContent='수입 자료가 변경되었습니다. 새로고침 후 다시 연결해 주세요.';notice.focus();}
    return;
   }
   if(notice)notice.hidden=true;
   var selected=localForm.querySelector('.participant-selected-income');
   if(selected)selected.remove();
   var lockedIncome=document.createElement('input');lockedIncome.type='hidden';lockedIncome.name='income_ref';lockedIncome.value=income.value;income.closest('label').replaceWith(lockedIncome);
   var participant=localForm.querySelector('[name=participant_id]');
   var options=Array.from(participant.options).filter(function(option){return option.value;});
   var chosen=document.createElement('input');chosen.type='hidden';chosen.name='participant_id';chosen.value=id||'';
   var group=document.createElement('fieldset');group.className='participant-inline-choices';
   group.setAttribute('aria-label','연결할 이름');
   options.forEach(function(option){
    var pick=document.createElement('button');pick.type='submit';pick.dataset.pickParticipant=option.value;pick.textContent=option.textContent;
    group.appendChild(pick);
   });
   localForm.querySelector('button[type=submit]').remove();
   participant.closest('label').replaceWith(chosen);localForm.appendChild(group);
   var first=Array.from(group.querySelectorAll('button')).find(function(button){return button.dataset.pickParticipant===id;})||group.querySelector('button');
   if(first)first.focus({preventScroll:true});
   row.scrollIntoView({block:'nearest'});
   return localForm;
  }
  document.addEventListener('submit',function(e){
   var target=e.target;
   if(!target.matches('form[action="/api/participants/link"],form[action="/api/participants/unlink"]') ||
      !(root.contains(target)||target.closest('.participant-insurance-cell,.insurance-candidate-row')))return;
   e.preventDefault();
   if(busy)return;
   var person=target.querySelector('[name=participant_id]');
   var pick=e.submitter;
   if(pick&&pick.hasAttribute('data-pick-participant')){
    person.value=pick.dataset.pickParticipant;
    if(person.value)write(target);
    return;
   }
   var label=person.tagName==='SELECT'?(person.selectedOptions[0]||{}).textContent:'';
   if(!person.value)return;
   ask(target.action.endsWith('/unlink')?'이 참가자 연결을 해제할까요?':'이 수입 기록을 '+(label||'선택한')+' 보험 참가자와 연결할까요?',function(){write(target);});
  });
  document.addEventListener('click',function(e){
   var connectButton=e.target.closest('[data-connect-income]');
   if(connectButton){
    var cell=connectButton.closest('.participant-insurance-cell');
    if(!cell)return;
    connectButton.disabled=true;
    loadPanel().then(function(){
     if(root.dataset.loaded==='1')choose(cell,null,true);
     else{root.open=true;var retry=root.querySelector('.participant-review-retry');if(retry)retry.focus();}
    }).finally(function(){if(connectButton.isConnected)connectButton.disabled=false;});
    return;
   }
   var evidenceButton=e.target.closest('[data-insurance-evidence]');
   if(evidenceButton){
    var evidence=root.querySelector('#'+CSS.escape(evidenceButton.dataset.insuranceEvidence));
    var existing=document.getElementById(evidenceButton.getAttribute('aria-controls'));
    if(existing){closeCandidates(existing,false);return;}
    if(evidence){
     var sourceRow=evidenceButton.closest('tr');
     var candidateRow=document.createElement('tr');
     candidateRow.className='insurance-candidate-row';candidateRow.id=evidenceButton.getAttribute('aria-controls');
     candidateRow.dataset.insuranceRowEvidence=evidenceButton.dataset.insuranceEvidence;
     var cell=document.createElement('td');
     cell.colSpan=Array.from(sourceRow.cells).reduce(function(total,item){return total+item.colSpan;},0);
     var evidenceContent=document.createElement('div');evidenceContent.className='insurance-candidate-content';
     evidenceContent.appendChild(evidence.content.cloneNode(true));
     var roster=evidenceContent.querySelector('[data-insurance-roster]'),rosterTemplate=root.querySelector('#insurance-roster-candidates');
     if(roster&&rosterTemplate)roster.replaceChildren(rosterTemplate.content.cloneNode(true));
     cell.appendChild(evidenceContent);candidateRow.appendChild(cell);sourceRow.after(candidateRow);
     evidenceButton.setAttribute('aria-expanded','true');
    }
    return;
   }
   var candidateConnect=e.target.closest('[data-insurance-participant]');
   if(candidateConnect){
    var candidateRow=candidateConnect.closest('.insurance-candidate-row');
    var targetCell=candidateRow&&candidateRow.previousElementSibling.querySelector('.participant-insurance-cell');
    if(targetCell){
     var participantId=candidateConnect.dataset.insuranceParticipant;
     closeCandidates(candidateRow,false);
     var selectedForm=choose(targetCell,participantId);
     var pick=selectedForm&&Array.from(selectedForm.querySelectorAll('[data-pick-participant]')).find(function(button){return button.dataset.pickParticipant===participantId;});
     if(pick)selectedForm.requestSubmit(pick);
    }
    return;
   }
   if(e.target.closest('.participant-review-retry')){loadPanel();return;}
   var jump=e.target.closest('a[href="#participant-trip-panel"]');
   if(jump){root.open=true;loadPanel();return;}
   var button=e.target.closest('[data-select-participant]');
   if(button&&form){
    form.querySelector('[name=participant_id]').value=button.dataset.selectParticipant;
    form.scrollIntoView({block:'nearest'});form.querySelector('[name=income_ref]').focus();
   }
  });
  document.addEventListener('dragover',function(e){var cell=e.target.closest('.participant-insurance-cell');if(cell&&root.dataset.dragParticipant){e.preventDefault();cell.classList.add('participant-drop-target');}});
  document.addEventListener('dragleave',function(e){var cell=e.target.closest('.participant-insurance-cell');if(cell)cell.classList.remove('participant-drop-target');});
  document.addEventListener('drop',function(e){
   var cell=e.target.closest('.participant-insurance-cell');if(!cell)return;
   e.preventDefault();cell.classList.remove('participant-drop-target');
   var id=root.dataset.dragParticipant;delete root.dataset.dragParticipant;
   if(!id||!form)return;var selectedForm=choose(cell,id);if(selectedForm)selectedForm.requestSubmit();
  });
  var loading=null;
  function loadPanel(){
   if(root.dataset.loaded==='1')return Promise.resolve();
   if(loading)return loading;
   delete root.dataset.loadFailed;
   root.setAttribute('aria-busy','true');
   var content=root.querySelector('[data-participant-content]');
   if(content)content.innerHTML='<div class="insurance-loading" role="status"><span class="insurance-loading-dot" aria-hidden="true"></span><div><strong>보험 명단과 수입을 대조하고 있습니다</strong><p>완료되면 수입 표에 결과가 표시됩니다.</p></div></div>';
   document.querySelectorAll('.participant-insurance-cell:not([data-income-refund-complete])').forEach(function(cell){cell.setAttribute('aria-busy','true');cell.innerHTML='<span class="insurance-loading-label">보험 명단 대조 중…</span>';});
   var q=new URLSearchParams({trip:root.dataset.trip||''}),current=new URLSearchParams(location.search);
   ['participant_q','participant_offset','participant_income_offset'].forEach(function(key){if(current.has(key))q.set(key,current.get(key));});
   var controller=new AbortController(),timeout=setTimeout(function(){controller.abort();},25000);
   loading=fetch('/api/participants/trip-panel?'+q.toString(),{headers:{'Accept':'text/html'},credentials:'same-origin',signal:controller.signal})
    .then(function(r){if(!r.ok)throw new Error();return r.text();})
    .then(function(markup){var doc=new DOMParser().parseFromString(markup,'text/html');var fresh=doc.querySelector('#participant-trip-panel');if(!fresh)throw new Error();root.innerHTML=fresh.innerHTML;root.dataset.loaded='1';bindPanel();})
    .catch(function(){root.dataset.loadFailed='1';root.open=true;var content=root.querySelector('[data-participant-content]');if(content)content.innerHTML='<p role="alert">보험 명단을 불러오지 못했습니다.</p><button type="button" class="participant-review-retry">다시 대조하기</button>';document.querySelectorAll('.participant-insurance-cell:not([data-income-refund-complete])').forEach(function(cell){cell.textContent='보험 영역에서 다시 불러와 주세요';});})
    .finally(function(){clearTimeout(timeout);loading=null;root.setAttribute('aria-busy','false');document.querySelectorAll('.participant-insurance-cell').forEach(function(cell){cell.removeAttribute('aria-busy');});});return loading;
  }
  root.addEventListener('toggle',function(){if(root.open&&!root.dataset.loadFailed)loadPanel();});
  if(location.hash==='#participant-trip-panel'||new URLSearchParams(location.search).has('participant_q'))root.open=true;
  if(root.dataset.autoLoad==='1')loadPanel();
 });
 var main=document.getElementById('main'), nav=document.getElementById('nav'),
     mask=document.getElementById('nav-mask');
 window.matchMedia('(min-width:900px)').addEventListener('change',function(event){
  if(!event.matches)document.querySelectorAll('.gemn-dialog[open]').forEach(function(dialog){dialog.close();});
 });
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
  var editorExitAnimation=null;
  function editorMotionAllowed(){
   return !window.matchMedia||!window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }
  function cancelEditorExit(){
   if(!editorExitAnimation)return;
   var active=editorExitAnimation;
   editorExitAnimation=null;
   active.onfinish=null;
   active.cancel();
  }
  function animateEditorOpen(slot){
   if(!slot||!slot.animate||!editorMotionAllowed())return;
   var height=slot.scrollHeight;
   if(!height)return;
   slot.animate([
    {height:'0px',opacity:0,overflow:'hidden'},
    {height:height+'px',opacity:1,overflow:'hidden'}
   ],{duration:220,easing:'cubic-bezier(.22,1,.36,1)'});
  }
  var drawerOpener=null;
  function placeEditor(id){
   cancelEditorExit();
   var slot=document.getElementById('panel-slot');
   var rows=document.querySelectorAll('.tw tr[data-id],.lst .li[data-id]'), target=null;
   for(var i=0;i<rows.length;i++) if(rows[i].dataset.id===id&&rows[i].getClientRects().length){target=rows[i];break;}
   if(!slot||!target)return false;
   var dialog=document.getElementById('ledger-drawer');
   if(dialog){
    drawerOpener=target;
    if(!dialog.contains(slot))(dialog.querySelector('.drawer-body')||dialog).appendChild(slot);
    document.querySelectorAll('[data-id][aria-expanded=true]').forEach(function(row){row.setAttribute('aria-expanded','false');row.removeAttribute('aria-controls');});
    target.setAttribute('aria-expanded','true');target.setAttribute('aria-controls','panel');
    if(!dialog.open)dialog.showModal();
    return true;
   }
   var old=slot.closest('.inline-editor-row,.inline-editor-mobile');
   if(old){document.querySelector('.app').appendChild(slot);old.remove();}
   document.querySelectorAll('[data-id][aria-expanded=true]').forEach(function(row){row.setAttribute('aria-expanded','false');row.removeAttribute('aria-controls');});
   var wrapper;
   if(target.tagName==='TR'){
    wrapper=document.createElement('tr');wrapper.className='inline-editor-row';
    var cell=document.createElement('td');cell.colSpan=target.cells.length;wrapper.appendChild(cell);cell.appendChild(slot);
   }else{wrapper=document.createElement('div');wrapper.className='inline-editor-mobile';wrapper.appendChild(slot);}
   target.insertAdjacentElement('afterend',wrapper);
   target.setAttribute('aria-expanded','true');target.setAttribute('aria-controls','panel');
   animateEditorOpen(slot);
   return true;
  }
  function removeEditor(animateClose,done){
   var slot=document.getElementById('panel-slot');
   if(!slot){if(done)done();return;}
   cancelEditorExit();
   var dialog=document.getElementById('ledger-drawer');
   if(dialog&&dialog.contains(slot)){
    if(dialog.open)dialog.close();
    slot.innerHTML='';
    document.querySelectorAll('[data-id][aria-expanded=true]').forEach(function(row){row.setAttribute('aria-expanded','false');row.removeAttribute('aria-controls');});
    if(drawerOpener&&drawerOpener.isConnected)drawerOpener.focus({preventScroll:true});
    if(done)done();
    return;
   }
   var wrapper=slot.closest('.inline-editor-row,.inline-editor-mobile');
   function finish(){
    editorExitAnimation=null;
    document.querySelector('.app').appendChild(slot);
    slot.innerHTML='';
    if(wrapper)wrapper.remove();
    document.querySelectorAll('[data-id][aria-expanded=true]').forEach(function(row){
     row.setAttribute('aria-expanded','false');row.removeAttribute('aria-controls');
    });
    if(done)done();
   }
   var height=wrapper?slot.getBoundingClientRect().height:0;
   if(animateClose&&wrapper&&height>0&&slot.animate&&editorMotionAllowed()){
    editorExitAnimation=slot.animate([
     {height:height+'px',opacity:1,overflow:'hidden'},
     {height:'0px',opacity:0,overflow:'hidden'}
    ],{duration:170,easing:'ease-in',fill:'forwards'});
    editorExitAnimation.onfinish=finish;
   }else finish();
  }
  var bulk=null;
  function bulkMark(){
   document.querySelectorAll('.tw tr[data-id],.lst .li[data-id]').forEach(function(row){
    var selected=!!(bulk&&bulk.selected.has(row.dataset.id));
    if(selected){row.dataset.bulkSelected='true';row.setAttribute(row.tagName==='BUTTON'?'aria-pressed':'aria-selected','true');}
    else{delete row.dataset.bulkSelected;if(bulk)row.setAttribute(row.tagName==='BUTTON'?'aria-pressed':'aria-selected','false');}
   });
   if(!bulk)return;
   var count=bulk.selected.size,total=0;bulk.selected.forEach(function(row){total+=row.amount;});
   bulk.bar.querySelector('[data-bulk-count]').textContent='선택 '+count+'건 · 합계 '+new Intl.NumberFormat('ko-KR').format(total)+'원';
   bulk.bar.querySelector('[data-bulk-save]').textContent=count+'건 변경';
   bulk.bar.querySelector('[data-bulk-save]').disabled=!count||!bulk.bar.querySelector('select').value||bulk.saving;
  }
  function bulkToggle(row,range){
   if(!bulk||bulk.saving||row.dataset.kind!=='expense')return;
   var visible=Array.from(document.querySelectorAll('.tw tr[data-kind="expense"],.lst .li[data-kind="expense"]')).filter(function(el){return el.getClientRects().length;});
   var ids=[row],i=visible.indexOf(row),last=visible.findIndex(function(el){return el.dataset.id===bulk.anchor;});
   if(range&&last>=0&&i>=0)ids=visible.slice(Math.min(last,i),Math.max(last,i)+1);
   var select=!bulk.selected.has(row.dataset.id);
   ids.forEach(function(el){if(select)bulk.selected.set(el.dataset.id,{id:el.dataset.id,revision:Number(el.dataset.revision),amount:Number(el.dataset.amount)});else bulk.selected.delete(el.dataset.id);});
   bulk.anchor=row.dataset.id;bulk.requestId='';bulkMark();
  }
  function startBulk(){
   var form=panelForm(),id=panelRow(),select=form&&form.querySelector('[name=display_tab_id]');
   if(!form||!select)return;
   var initial=select.querySelector('option[selected]');
   var values=select.innerHTML,chosen=select.value!==(initial?initial.value:'')?select.value:'';
   if(!canLeavePanel('여행 선택을 유지하고 다른 편집 내용은 취소할까요?'))return;
   var row=Array.from(document.querySelectorAll('[data-id]')).find(function(el){return el.dataset.id===id&&el.getClientRects().length;});
   if(!row)return;
   releasePanel();removeEditor();setRowParam('');
   var bar=document.createElement('div');bar.className='bulk-bar';bar.setAttribute('role','region');bar.setAttribute('aria-label','선택 거래 일괄 변경');
   bar.innerHTML='<strong data-bulk-count aria-live="polite"></strong><label for="bulk-search">여행 검색</label><input id="bulk-search" type="search" autocomplete="off"><label for="bulk-trip">변경할 여행</label><select id="bulk-trip" aria-label="변경할 여행"></select><button type="button" class="btn primary" data-bulk-save disabled>0건 변경</button><button type="button" class="btn" data-bulk-end>선택 종료</button><span data-bulk-status role="status" aria-live="polite"></span>';
   document.body.appendChild(bar);bar.querySelector('select').innerHTML=values;
   var empty=bar.querySelector('select option[value=""]');if(empty)empty.textContent='변경할 여행 선택';
   bar.querySelector('select').value=chosen;
   bulk={selected:new Map(),bar:bar,anchor:id,saving:false};document.body.classList.add('bulk-selecting');
   var scrollArea=main.closest('.main')||main;
   if(window.ResizeObserver){bulk.observer=new ResizeObserver(function(){scrollArea.style.setProperty('--bulk-bar-height',(bar.getBoundingClientRect().height+24)+'px');});bulk.observer.observe(bar);}
   bulkToggle(row,false);bar.querySelector('select').focus();
  }
  function endBulk(){
   if(!bulk||bulk.saving)return;
   var bar=bulk.bar;if(bulk.observer)bulk.observer.disconnect();bulk=null;document.body.classList.remove('bulk-selecting');(main.closest('.main')||main).style.removeProperty('--bulk-bar-height');bar.remove();
   document.querySelectorAll('[data-id]').forEach(function(row){delete row.dataset.bulkSelected;row.removeAttribute('aria-selected');row.removeAttribute('aria-pressed');});
   window.dispatchEvent(new Event('ledger:saved'));
  }
  function saveBulk(){
   if(!bulk||bulk.saving||!bulk.selected.size)return;
   var state=bulk,select=state.bar.querySelector('select'),target=select.value;
   if(!target)return;
   if(!window.confirm(state.selected.size+'건의 여행을 '+select.selectedOptions[0].textContent+'(으)로 변경할까요? 비용 항목은 유지됩니다.'))return;
   if(!state.requestId)state.requestId=(window.crypto&&window.crypto.randomUUID)?window.crypto.randomUUID():String(Date.now())+'-'+String(Math.random()).slice(2);
   var rows=Array.from(state.selected.values()).map(function(row){return {row_id:row.id,revision:row.revision};});
   state.saving=true;select.disabled=true;bulkMark();
   state.bar.querySelector('[data-bulk-status]').textContent='저장 중입니다.';
   post('/api/rows/bulk-trip',{rows:rows,target:target,client_request_id:state.requestId}).then(function(res){
    if(res.ok&&res.body.outcome==='saved'){
     state.saving=false;endBulk();
     var next=new URL(location.href);next.searchParams.delete('row');
     next.searchParams.set('msg',res.body.count+'건을 변경했습니다. 여행이 바뀐 거래는 현재 목록에서 빠질 수 있습니다.');
     location.href=next.toString();return;
    }
    var error=res.body||{};
    state.bar.querySelector('[data-bulk-status]').textContent=(error.row_id?'거래 '+error.row_id+': ':'')+(error.message||'저장하지 못했어요. 선택은 유지됩니다.');
   }).catch(function(){state.bar.querySelector('[data-bulk-status]').textContent='응답을 확인하지 못했어요. 같은 선택으로 다시 시도해 주세요.';})
    .finally(function(){state.saving=false;select.disabled=false;bulkMark();});
  }
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
   if(bulk){bulkMark();return;}
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
    prev.hidden=true;next.hidden=true;if(count.textContent!=='')count.textContent='';return;
   }
   // A button with no row to walk to is not shown at all. One row of six is a
   // real position and is still said; the two ends of a one row list are the
   // same row, so offering them would be offering a move that cannot happen.
   prev.hidden=(i<=0);
   next.hidden=(i>=ids.length-1);
   var position=(i+1)+' / '+ids.length;
   if(count.textContent!==position)count.textContent=position;
  }
  var panelLoading=false;
  function openPanel(id){
   // The row that is already open needs no panel and no question: re-fetching it
   // would throw away what was typed for no gain.
   if(!id) return;
   if(id===panelRow()){closePanel();return;}
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
     if(!placeEditor(id))throw new Error('ROW_NOT_FOUND');
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
   setRowParam('');
   removeEditor(true,function(){
    markSelection();window.dispatchEvent(new Event('ledger:saved'));
   });
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
  function canLeavePanel(message){
   if(panelLoading) return false;
   if(document.querySelector('form[data-saving="1"]')){
    var slot=(panelForm()&&panelForm().querySelector('.f-msg'))||
     document.getElementById('status');
    say(slot,'저장하는 중이에요. 저장이 끝난 뒤 이동해 주세요',false);
    return false;
   }
   var f=panelForm();
   if(f&&f.getAttribute('data-dirty')&&!window.confirm(
    message||'저장하지 않은 변경이 있어요. 저장하지 않고 이동할까요?')) return false;
   return true;
  }
  document.addEventListener('ledger:open-row',function(event){
   var detail=event.detail||{};
   if(bulk){if(detail.row)bulkToggle(detail.row,detail.range);return;}
   openPanel(detail.id);
  });
  document.addEventListener('ledger:close-panel',closePanel);
  var ledgerDrawer=document.getElementById('ledger-drawer');
  if(ledgerDrawer)ledgerDrawer.addEventListener('cancel',function(event){event.preventDefault();closePanel();});
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
   if(e.target.closest('#bulk-start')){e.preventDefault();startBulk();return;}
   if(e.target.closest('[data-bulk-save]')){e.preventDefault();saveBulk();return;}
   if(e.target.closest('[data-bulk-end]')){endBulk();return;}
   if(e.target.closest('#p-cancel')){e.preventDefault();closePanel();return;}
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
  if(e.target.closest('[data-gemn-close]')){e.target.closest('dialog').close();return;}
  var groupButton=e.target.closest('[data-gemn-group]');
  if(groupButton){
   e.preventDefault();
   var groupDetail=document.getElementById(groupButton.getAttribute('data-gemn-group'));
   if(groupDetail){var groupDialog=groupDetail.closest('dialog');
    if(groupDialog){groupDialog.querySelectorAll('details').forEach(function(detail){detail.hidden=detail!==groupDetail;});groupDialog.showModal();}
    groupDetail.open=true;var groupSummary=groupDetail.querySelector('summary');
    if(groupSummary){groupSummary.focus();groupSummary.scrollIntoView({block:'nearest'});}}
   return;
  }
  if(e.target.closest('a,button,input,select,textarea')&&!e.target.closest('.li[data-id]'))return;
  var row=e.target.closest('tr[data-id]');
  if(row){e.preventDefault();if(bulk)bulkToggle(row,e.shiftKey);else openPanel(row.dataset.id);return;}
  var item=e.target.closest('.li[data-id]');
  if(item){e.preventDefault();if(bulk)bulkToggle(item,e.shiftKey);else openPanel(item.dataset.id);return;}
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
     if(body.revision)document.querySelectorAll('[data-id]').forEach(function(row){
      if(row.dataset.id===body.row_id)row.dataset.revision=String(body.revision);
     });
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
      say(slot,'저장했습니다',false);
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
   var disclosure=input.closest('details');
   while(disclosure){disclosure.open=true;disclosure=disclosure.parentElement.closest('details');}
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
      if(bulk)bulkToggle(tr,e.shiftKey);else openPanel(tr.getAttribute('data-id'));
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
     if(tag==='textarea'||tag==='summary') return;
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
     removeEditor();setRowParam('');markSelection();window.dispatchEvent(new Event('ledger:saved'));
    }
   });
  // A finished save, and a row list that another screen replaced, both mean the
  // selection and the position beside the walking buttons have to be read again.
  window.addEventListener('ledger:saved',function(){markSelection();syncNav();});
  // PR-4 keeps the editor in the native ledger drawer; it is not moved beside
  // the clicked row.
  window.addEventListener('resize',function(){
   window.requestAnimationFrame(function(){
    var id=panelRow(), slot=document.getElementById('panel-slot');
    if(id&&slot&&!slot.getClientRects().length)placeEditor(id);
   });
  });
  var region=document.getElementById('live-rows');
  if(region&&window.MutationObserver){
   new MutationObserver(function(){markSelection();syncNav();})
    .observe(region,{childList:true,subtree:true});
  }
  // Any change marks the panel dirty so Escape knows to ask.
  document.addEventListener('input',function(e){
   if(e.target.id==='f-trip-search'||e.target.id==='bulk-search'){
    var target=e.target.id==='f-trip-search'?document.getElementById('f-display_tab_id'):document.getElementById('bulk-trip');
    if(target){var query=e.target.value.trim().toLocaleLowerCase();Array.from(target.options).forEach(function(option){option.hidden=!!option.value&&option.value!==target.value&&!option.textContent.toLocaleLowerCase().includes(query);});}
    return;
   }
   var form=e.target.closest&&e.target.closest('form[data-js-save]');
   if(form) markDirty(form);
  });
  document.addEventListener('change',function(e){if(bulk&&e.target===bulk.bar.querySelector('select')){bulk.requestId='';bulkMark();}});
  // A finished save leaves nothing unsaved.
  document.addEventListener('submit',function(e){
   var form=e.target;
   if(form.matches&&form.matches('form[data-js-save]')) clearFlags(form);
  },true);

  // Trip tab expense copy button (contract: Google 7-column B:H TSV copy)
  document.addEventListener('click',async function(e){
   if(e.target.closest&&e.target.closest('[data-copy-recheck]')){location.reload();return;}
   var close=e.target.closest&&e.target.closest('[data-copy-text-close]');
   if(close){
    var card=close.closest('.trip-copy-wrap');
    card.querySelector('.trip-copy-manual').hidden=true;
    card.querySelector('#copy-trip-expenses,[data-copy-trip-tsv]').focus();
    return;
   }
   var retry=e.target.closest&&e.target.closest('[data-copy-prepared]');
   var btn=e.target.closest&&e.target.closest('#copy-trip-expenses,[data-copy-trip-tsv]');
   btn=retry||btn;
   if(!btn||btn.disabled) return;
   var wrap=btn.closest('.trip-copy-wrap')||btn.parentNode;
   if(wrap.getAttribute('aria-busy')==='true')return;
   var original=wrap.querySelector('#copy-trip-expenses,[data-copy-trip-tsv]');
   var tab=original&&original.getAttribute('data-tab');
   if(!tab) return;
   var status=wrap&&wrap.querySelector('.copy-status');
   var manual=wrap.querySelector('.trip-copy-manual');
   var prepared=manual&&manual.querySelector('textarea');
   function notice(message,state){
    if(status){status.textContent=message;status.className='copy-status'+(state?' '+state:'');}
   }
   function selectPrepared(){
    manual.hidden=false;prepared.focus();prepared.select();prepared.setSelectionRange(0,prepared.value.length);
   }
   function updateExclusions(data){
    var detail=wrap.querySelector('.trip-copy-hold-details');
    if(!detail)return;
    var held=data.held||[],rows=(data.reconciliation||{}).cost_rows||[];
    detail.replaceChildren();detail.hidden=!held.length;
    var summary=document.createElement('summary');
    summary.textContent='복사 제외 거래 '+held.length+'건 보기';detail.appendChild(summary);
    var explanation=document.createElement('p');
    explanation.textContent='이번 복사에서 제외된 거래입니다. 거래 상세에서 Google 장부 대조 근거와 원본을 비교하세요.';
    detail.appendChild(explanation);
    var list=document.createElement('ul');list.className='trip-copy-excluded';
    held.forEach(function(item){
     var row=rows.find(function(row){return String(row.transaction_id)===String(item.transaction_id);})||{};
     var li=document.createElement('li');
     li.textContent=[row.occurred_on||row.date||'날짜 없음',row.merchant||item.transaction_id||'거래 식별 정보 없음',
      row.amount_krw==null?'금액 없음':Number(row.amount_krw).toLocaleString('ko-KR')+'원'].join(' · ');
     if(row.row_id){var link=document.createElement('a');link.href='/row?id='+encodeURIComponent(row.row_id);
      link.textContent='거래 상세 보기';li.appendChild(document.createTextNode(' '));li.appendChild(link);}
     list.appendChild(li);
    });
    detail.appendChild(list);
   }
   async function copyText(value){
    // Select the real, visible TSV before copying. Native copy completes in the
    // current gesture and cannot leave the UI waiting on a clipboard promise.
    selectPrepared();
    try{if(document.execCommand('copy'))return true;}catch(error){}
    if(!navigator.clipboard||!navigator.clipboard.writeText)return false;
    // Some browsers neither resolve nor reject writeText after an async fetch.
    // Bound that optional attempt; a late settlement must not change the UI.
    var clipboardTimer;
    try{
     return await Promise.race([
      navigator.clipboard.writeText(value).then(function(){return true;},function(){return false;}),
      new Promise(function(resolve){clipboardTimer=setTimeout(function(){resolve(false);},1500);})
     ]);
    }catch(error){return false;}
    finally{clearTimeout(clipboardTimer);}
   }
   btn.disabled=true;
   wrap.setAttribute('aria-busy','true');
   var timer;
   try{
    var data;
    if(!retry){
     notice('Google 장부와 대조해 복사할 내용을 준비하고 있습니다…','loading');
     manual.hidden=true;prepared.value='';
     var filters=new URLSearchParams(location.search),params=new URLSearchParams();
     ['q','kind'].forEach(function(key){if(filters.has(key)) params.set(key,filters.get(key));});
     var controller=new AbortController();
     timer=setTimeout(function(){controller.abort();},45000);
     // The existing owner-only GET returns freshly deduplicated B:H TSV and
     // writes neither reconciliation links nor financial/Google records.
     var res=await fetch('/api/tabs/'+encodeURIComponent(tab)+'/tsv'+(params.size?'?'+params.toString():''),
                         {credentials:'same-origin',cache:'no-store',signal:controller.signal});
     try{data=await res.json();}catch(parseError){
      throw new Error('복사할 내용을 받지 못했습니다. 잠시 후 다시 복사해 주세요.');
     }
     if(!res.ok)throw new Error(data.message||'지출내용을 준비하지 못했습니다. 다시 복사해 주세요.');
     if(!data.source_available){
      throw new Error('Google 장부를 확인하지 못했습니다. 장부를 동기화한 뒤 다시 복사해 주세요.');
     }
     updateExclusions(data);
     if(data.row_count===0){
      notice(data.held&&data.held.length?'복사할 수 있는 지출이 없습니다. 아래 제외 내역에서 거래와 Google 기록을 비교해 주세요.':
             data.matched&&data.matched.length?'모든 지출이 장부에 있어 복사할 항목이 없습니다.':'복사할 지출이 없습니다.');
      return;
     }
     if(typeof data.tsv!=='string'||!data.tsv||!Number.isInteger(data.row_count)||data.row_count<1){
      throw new Error('복사할 내용을 확인하지 못했습니다. 다시 복사해 주세요.');
     }
     prepared.value=data.tsv;
     prepared.dataset.count=String(data.row_count);
     prepared.dataset.total=String(data.total_krw||0);
     prepared.dataset.matched=String((data.matched||[]).length);
     prepared.dataset.held=String((data.held||[]).length);
    }
    if(!prepared.value)return;
    clearTimeout(timer);
    notice('복사할 내용이 준비됐습니다. 클립보드에 복사하고 있습니다…','loading');
    if(!await copyText(prepared.value)){
     selectPrepared();
     notice('복사할 내용이 준비됐습니다. 선택된 내용을 복사(Ctrl+C 또는 ⌘C)하거나 다시 복사를 누른 뒤 Google 시트에 붙여넣으세요.');
     return;
    }
    manual.hidden=true;
    try{localStorage.setItem('gcopy-trip:'+tab,new Date().toLocaleString('ko-KR'));}catch(error){}
    var sum=Number(prepared.dataset.total||0),held=Number(prepared.dataset.held||0),matched=Number(prepared.dataset.matched||0);
    notice('지출내용이 복사되었습니다. '+prepared.dataset.count+'건'+(sum?' · '+sum.toLocaleString('ko-KR')+'원':'')+
           '. Google 시트에 붙여넣으세요.'+(matched?' 이미 기록된 '+matched+'건 제외.':'')+
           (held?' 중복 가능성 등으로 제외된 '+held+'건은 아래 내역에서 확인하세요.':''),'success');
   }catch(err){
    notice(err.name==='AbortError'?'내용 준비가 지연되고 있습니다. 잠시 후 다시 복사해 주세요.':
           err instanceof TypeError?'연결을 확인한 뒤 다시 복사해 주세요.':(err.message||'내용을 준비하지 못했습니다. 다시 복사해 주세요.'),'err');
   }finally{
    clearTimeout(timer);btn.disabled=false;wrap.removeAttribute('aria-busy');
    if(!manual.hidden)prepared.focus({preventScroll:true});
    else original.focus({preventScroll:true});
   }
  });
 })();
(function(){
 document.addEventListener('DOMContentLoaded',function(){
  var dialog=document.getElementById('manual-expense-dialog');
  if(!dialog)return;
  var form=dialog.querySelector('form'),busy=false,opener=null;
  document.addEventListener('click',function(event){
   var trigger=event.target.closest('[data-manual-open]');
   if(!trigger)return;
   event.preventDefault();opener=trigger;dialog.showModal();
  });
  dialog.querySelector('[data-manual-close]').addEventListener('click',function(){if(!busy)dialog.close();});
  dialog.addEventListener('cancel',function(event){if(busy)event.preventDefault();});
  dialog.addEventListener('close',function(){if(opener&&opener.isConnected)opener.focus();});
  form.addEventListener('submit',async function(event){
   event.preventDefault();if(busy)return;
   var payload=Object.fromEntries(new FormData(form));
   busy=true;form.setAttribute('aria-busy','true');
   // Freeze inputs too: a network retry must repeat the same request identity
   // and values, and a late response must not discard newly edited fields.
   var controls=Array.from(form.elements);controls.forEach(function(c){c.disabled=true;});
   var status=form.querySelector('.mx-error');status.textContent='';
   try{
    var response=await fetch(form.action,{method:'POST',credentials:'same-origin',
     headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(payload)});
    var result=await response.json();
    if(!response.ok)throw new Error(result.message||'저장하지 못했습니다. 다시 시도해 주세요.');
    location.reload();
   }catch(error){status.textContent=error.message||'저장하지 못했습니다. 다시 시도해 주세요.';
    busy=false;controls.forEach(function(c){c.disabled=false;});form.removeAttribute('aria-busy');}
  });
 });
})();

/* Excluded-from-copy rows: open the transaction detail in place (no page change). */
(function(){
 function rowButton(rowId){
  var row=rowId&&document.querySelector('[data-id="'+CSS.escape(rowId)+'"]');
  if(!row)return null;
  var b=document.createElement('button');b.type='button';b.className='btn';b.textContent='장부 행 상세 열기';
  b.addEventListener('click',function(){row.scrollIntoView({block:'center'});row.click();});
  return b;
 }
 function message(panel,text,rowId){
  panel.replaceChildren();
  var p=document.createElement('p');p.className='copy-held-note';p.textContent=text;panel.append(p);
  var b=rowButton(rowId);if(b)panel.append(b);
 }
 document.addEventListener('click',async function(event){
  var button=event.target.closest&&event.target.closest('.copy-held-toggle');
  if(!button)return;
  var panel=document.getElementById(button.getAttribute('aria-controls'));
  if(!panel)return;
  var open=button.getAttribute('aria-expanded')==='true';
  button.setAttribute('aria-expanded',String(!open));panel.hidden=open;
  if(open||panel.dataset.loaded==='1')return;
  var id=button.dataset.transactionId,rowId=button.dataset.rowId;
  if(!id){message(panel,'카드 거래가 아니어서 이 자리에서 상세를 불러올 수 없습니다.',rowId);return;}
  panel.setAttribute('aria-busy','true');message(panel,'상세를 불러오는 중입니다.',null);
  try{
   var response=await fetch('/api/cards/transactions/detail?'+new URLSearchParams({id:id}),{headers:{'Accept':'application/json'},credentials:'same-origin'});
   if(response.status===404){message(panel,'카드 거래 상세가 없는 행입니다. 장부 행 상세에서 확인하세요.',rowId);}
   else if(!response.ok){message(panel,'상세를 불러오지 못했습니다. 잠시 뒤 다시 펼쳐 보세요.',rowId);panel.removeAttribute('aria-busy');return;}
   else{var data=await response.json();panel.innerHTML=data.html||'';var b=rowButton(rowId);if(b)panel.append(b);}
   panel.dataset.loaded='1';
  }catch(error){message(panel,'연결이 끊겨 상세를 불러오지 못했습니다. 다시 펼쳐 보세요.',rowId);}
  panel.removeAttribute('aria-busy');
 });
})();
