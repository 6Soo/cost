(()=> {
 const actionIcons=__ACTION_ICONS__;
 const iconRules=[
  [/검색|조회|찾기/,'search'],[/업로드|파일 추가|가져오기/,'upload'],
  [/저장된|자료 선택|목록|내역/,'list'],[/복사|붙여넣/,'copy'],
  [/초기화|되돌|복원/,'rotate-ccw'],[/새로|동기화|갱신|재시도/,'refresh-cw'],
  [/삭제|제거|해제|제외/,'circle-minus'],[/취소|닫기/,'x-circle'],
  [/저장/,'save'],[/수정|편집|교정/,'pencil'],[/추가|등록|입력/,'pencil'],
  [/연결/,'link'],[/다운로드|내보내기|출력/,'table'],
  [/이전|돌아|뒤로/,'chevron-left'],[/다음|열기|보기|상세|이동|검토/,'chevron-right'],
  [/적용|완료|선택|확인|기록/,'check']
 ];
 const actionLink=/검색|조회|초기화|돌아가기|장부로|장부 보기|상세|검토|다운로드|내보내기|추가|업로드|수정|관리|전체 보기|더 보기|이전|다음|새 창|원본|설정/;
 function decorate(el){
  if(el.closest('#nav,[role="tablist"],.site-theme-bar,.site-bottom-nav,.site-more-dialog')||el.matches('.site-back,.site-more-toggle,.site-more-bottom,#site-theme-toggle'))return;
  if(el.matches('.participant-row-connect,.participant-link-details > summary,.insurance-candidate-button,.insurance-participant-name,[data-pick-participant]'))return;
  if(el.matches('#flight-booking-page summary,.card-all-row-toggle,.cleanup-review > summary'))return;
  if(el.tagName==='SUMMARY'&&el.querySelector('svg,img,button,[role="button"]'))return;
  const text=el.textContent.trim();
  if(!/[가-힣A-Za-z]/.test(text))return;
  if(el.tagName==='A'){
   const explicit=el.matches('.btn,.catalog-btn,.header-button,[role="button"]');
   const rowAction=/^(상세|검토|수정|편집|원본|장부|근거|복사|연결|해제|보기|이전|다음)/.test(text);
   if((!explicit&&(el.closest('h1,h2,h3,h4,label')||(el.closest('td,th')&&!rowAction)))||(!explicit&&!actionLink.test(text))||text.length>65)return;
   const href=el.getAttribute('href')||'';
   if(!href||/^(mailto:|tel:|javascript:)/i.test(href))return;
  }
  el.classList.add('site-action');
  if(el.querySelector('svg,img,.ic'))return;
  const found=iconRules.find(([pattern])=>pattern.test(text));
  const name=found?found[1]:(el.tagName==='SUMMARY'?'chevron-down':'chevron-right');
  const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+(actionIcons[name]||'')+'</svg>';
  el.style.setProperty('--action-icon','url("data:image/svg+xml,'+encodeURIComponent(svg)+'")');
  el.classList.add('site-action-icon');
 }
 function decorateTree(root){
  if(!(root instanceof Element))return;
  if(root.matches('button,summary,a[href]'))decorate(root);
  root.querySelectorAll('button,summary,a[href]').forEach(decorate);
 }
 decorateTree(document.body);
 const observer=new MutationObserver(records=>{
  const roots=new Set();
  records.forEach(record=>{
   const parent=record.target.nodeType===Node.TEXT_NODE?record.target.parentElement:record.target;
   const control=parent&&parent.closest?parent.closest('button,summary,a[href]'):null;
   if(control)roots.add(control);
   record.addedNodes.forEach(node=>{if(node instanceof Element)roots.add(node)});
  });
  roots.forEach(decorateTree);
 });
 observer.observe(document.body,{childList:true,subtree:true,characterData:true});
 const dialog=document.getElementById('site-more-dialog');
 const openers=document.querySelectorAll('.site-more-toggle,.site-more-bottom');
 const closeDialog=()=>{if(dialog&&dialog.open)dialog.close();if(dialog)dialog.inert=true};
 if(dialog)dialog.inert=true;
 openers.forEach(button=>button.addEventListener('click',()=>{if(dialog&&!dialog.open){dialog.inert=false;dialog.showModal()}}));
 dialog?.addEventListener('close',()=>{dialog.inert=true});
 dialog?.addEventListener('cancel',event=>{event.preventDefault();closeDialog()});
 dialog?.addEventListener('click',event=>{if(event.target===dialog)closeDialog()});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&dialog?.open)closeDialog()});
})();
