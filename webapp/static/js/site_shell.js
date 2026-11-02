(()=>{
 // Pseudo-element icons leave textContent, child nodes and action handlers intact.
 // Observe replacements as well as initial HTML: review rows load asynchronously.
 const actionIcons=__ACTION_ICONS__;
 const iconRules=[
  [/検索|검색|조회|찾기/,'search'],[/업로드|파일 추가|가져오기/,'upload'],
  [/저장된|자료 선택|목록|내역/,'list'],[/복사|붙여넣/,'copy'],
  [/초기화|되돌|복원/,'rotate-ccw'],[/새로|동기화|갱신|재시도/,'refresh-cw'],
  [/삭제|제거|해제|제외/,'circle-minus'],[/취소|닫기/,'x-circle'],
  [/저장/,'save'],[/수정|편집|교정/,'pencil'],[/추가|등록|입력/,'pencil'],
  [/연결/,'link'],[/다운로드|내보내기|출력/,'table'],
  [/이전|돌아|뒤로/,'chevron-left'],[/다음|열기|보기|상세|이동|검토/,'chevron-right'],
  [/적용|완료|선택|확인|기록/,'check']
 ];
 const actionLink=/검색|조회|초기화|돌아가기|장부로|장부 보기|상세|검토|다운로드|내보내기|추가|업로드|수정|관리|전체 보기|더 보기|이전|다음|새 창|원본|설정/;
 function decorateAction(el){
  if(el.closest('#nav,[role="tablist"],.site-theme-bar')||el.matches('#btn-menu,.site-menu-toggle'))return;
  // This inline disclosure owns its compact row height, chevron and focus style.
  if(el.matches('.participant-link-details > summary'))return;
  // A compound disclosure already exposes its own button; avoid a second frame.
  if(el.tagName==='SUMMARY'&&el.querySelector('svg,img,button,[role="button"]'))return;
  const text=el.textContent.trim();
  // Numeric pages, disclosure arrows and accessible icon-only controls stay compact.
  if(!/[가-힣A-Za-z]/.test(text))return;
  if(el.tagName==='A'){
   const explicit=el.matches('.btn,.catalog-btn,.header-button,[role="button"]');
   const rowAction=/^(상세|검토|수정|편집|원본|장부|근거|복사|연결|해제|보기|이전|다음)/.test(text);
   if((!explicit&&(el.closest('h1,h2,h3,h4,label')||(el.closest('td,th')&&!rowAction)))||(!explicit&&!actionLink.test(text))||text.length>65)return;
   const href=el.getAttribute('href')||'';
   if(!href||/^(mailto:|tel:|javascript:)/i.test(href))return;
  }
  el.classList.add('site-action');
  if(el.querySelector('svg,img,.ic')){el.classList.remove('site-action-icon');return;}
  const name=iconRules.find(([pattern])=>pattern.test(text))?.[1]||(el.tagName==='SUMMARY'?'list':'chevron-right');
  const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+actionIcons[name]+'</svg>';
  el.style.setProperty('--action-icon','url("data:image/svg+xml,'+encodeURIComponent(svg)+'")');
  el.classList.add('site-action-icon');
 }
 function decorateTree(root){
  if(!(root instanceof Element))return;
  if(root.matches('button,summary,a[href]'))decorateAction(root);
  root.querySelectorAll('button,summary,a[href]').forEach(decorateAction);
 }
 decorateTree(document.body);
 new MutationObserver(records=>{
  const roots=new Set();
  for(const record of records){
   const parent=record.target.nodeType===Node.TEXT_NODE?record.target.parentElement:record.target;
   const control=parent?.closest?.('button,summary,a[href]');if(control)roots.add(control);
   for(const node of record.addedNodes)if(node instanceof Element)roots.add(node);
  }
  roots.forEach(decorateTree);
 }).observe(document.body,{childList:true,subtree:true,characterData:true});
 const nav=document.getElementById('nav'),mask=document.getElementById('nav-mask');if(!nav)return;
 const buttons=document.querySelectorAll('.site-menu-toggle,#btn-menu');let menuTrigger=null;
const close=({restoreFocus=false}={})=>{nav.classList.remove('open');if(mask)mask.hidden=true;buttons.forEach(b=>b.setAttribute('aria-expanded','false'));if(restoreFocus){const target=menuTrigger&&menuTrigger.getClientRects().length?menuTrigger:[...buttons].find(b=>b.getClientRects().length);target?.focus()}menuTrigger=null};
 buttons.forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();const open=!nav.classList.contains('open');
 if(open)menuTrigger=b;
 nav.classList.toggle('open',open);if(mask)mask.hidden=!open;b.setAttribute('aria-expanded',String(open));
 if(open)nav.querySelector('a,input')?.focus()}));
 mask?.addEventListener('click',close);
 nav.addEventListener('keydown',e=>{if(e.key==='Tab'&&nav.classList.contains('open')){const items=[...nav.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),summary')].filter(el=>el.getClientRects().length);if(!items.length)return;const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&nav.classList.contains('open'))close({restoreFocus:true})});
 const path=location.pathname;
 // Restore only a view's own GET filters; stored state never performs a write.
 try{
 const filterPaths=new Set(['/cards/all','/ota','/reserve-links','/trips','/flight-passengers']);
 if(filterPaths.has(path)&&location.search)sessionStorage.setItem('cost-view:'+path,location.search);
 nav.querySelectorAll('.site-links a[href]').forEach(a=>{const u=new URL(a.href,location.href);if(filterPaths.has(u.pathname)&&!u.search){const saved=sessionStorage.getItem('cost-view:'+u.pathname);if(saved&&saved.startsWith('?'))a.search=saved}});
 const params=new URLSearchParams(location.search),main=document.querySelector('main'),explicit=params.get('trip')||params.get('tab');
 if(path==='/board'&&params.get('tab'))sessionStorage.setItem('cost-workflow-return',location.pathname+location.search);
 const stored=sessionStorage.getItem('cost-workflow-return');
 let back=explicit&&(!stored||new URL(stored,location.origin).searchParams.get('tab')!==explicit)?'/board?'+new URLSearchParams({tab:explicit}):stored;
 if(back){const selected=new URL(back,location.origin).searchParams.get('tab');if(selected)nav.querySelectorAll('.site-links a[href]').forEach(a=>{const u=new URL(a.href);if(['/receipts','/trips','/reserve-links','/flight-passengers'].includes(u.pathname)&&(!u.search||(path==='/board'&&explicit&&u.pathname==='/trips')))a.search=new URLSearchParams({trip:selected}).toString()})}
 if(back){const u=new URL(back,location.origin);if(u.origin!==location.origin||u.pathname!=='/board')back=null}
 const tools=new Set(['/receipts','/trips','/reserve-links','/flight-passengers','/participants','/participants/insurance-match','/export','/expense/new','/ota','/row','/rules']);
 if(back&&tools.has(path)){
 const existing=[...document.querySelectorAll('a[href="/board"],a[href="/board?tab="]')].find(a=>!a.closest('#nav'));
 document.querySelectorAll('a[href="/board"],a[href="/board?tab="]').forEach(a=>{if(!a.closest('#nav'))a.href=back});
 const host=document.querySelector('#site-content')||main;
 if(existing){existing.setAttribute('aria-label',explicit?'선택한 여행 장부로 돌아가기':'최근 여행 장부로 돌아가기')}
 else if(host){const bar=document.createElement('nav');bar.className='workflow-return';bar.setAttribute('aria-label','현재 업무로 돌아가기');const link=document.createElement('a');link.href=back;link.textContent=explicit?'선택한 여행 장부로 돌아가기':'최근 여행 장부로 돌아가기';bar.append(link);const header=host.querySelector('.site-topbar');if(header)header.after(bar);else host.prepend(bar)}
 }
 }catch{}
 const tripFilter=document.getElementById('trip-management-filter');
 if(tripFilter){const search=document.getElementById('trip-management-search'),state=document.getElementById('trip-management-state'),owner=document.getElementById('trip-management-owner'),rows=[...document.querySelectorAll('.trip-management-row')],params=new URLSearchParams(location.search);
 search.value=params.get('q')||'';state.value=params.get('state')||'';if(owner)owner.value=['aslan','andre'].includes(params.get('owner'))?params.get('owner'):'';
 const selected=params.get('trip');
 if(selected&&!search.value){const row=rows.find(r=>r.dataset.tripId===selected);if(row)search.value=row.querySelector('h3 a').textContent}
 const update=()=>{const term=search.value.trim().toLocaleLowerCase();let count=0;rows.forEach(row=>{row.hidden=!(row.dataset.tripSearch.toLocaleLowerCase().includes(term)&&(!state.value||row.dataset.archived===state.value)&&(!owner?.value||row.dataset.owner===owner.value));if(!row.hidden)count++});document.getElementById('trip-management-count').textContent=count+'개 여행';document.getElementById('trip-management-empty').hidden=count>0;
 const u=new URL(location.href);u.searchParams.delete('trip');if(search.value)u.searchParams.set('q',search.value);else u.searchParams.delete('q');if(state.value)u.searchParams.set('state',state.value);else u.searchParams.delete('state');if(owner?.value)u.searchParams.set('owner',owner.value);else u.searchParams.delete('owner');history.replaceState(null,'',u.pathname+u.search+u.hash);try{sessionStorage.setItem('cost-view:/trips',u.search)}catch{}};
 tripFilter.addEventListener('submit',e=>e.preventDefault());search.addEventListener('input',update);state.addEventListener('change',update);owner?.addEventListener('change',update);tripFilter.addEventListener('reset',()=>{search.value='';state.value='';if(owner)owner.value='';update()});update();
 }
 const exportForm=document.querySelector('form[action="/api/exports/xlsx"]');
 if(exportForm&&document.getElementById('export-selection-count')){const boxes=[...exportForm.querySelectorAll('input[name="tab_ids"]')];const update=()=>{const n=boxes.filter(b=>b.checked).length;document.getElementById('export-selection-count').textContent=n+'개 여행 선택';exportForm.querySelector('button[type="submit"]').disabled=n===0};exportForm.querySelectorAll('[data-export-select]').forEach(b=>b.addEventListener('click',()=>{boxes.forEach(box=>box.checked=b.dataset.exportSelect==='all');update()}));exportForm.addEventListener('change',update);update()}
 nav.querySelectorAll('a[href]').forEach(a=>{const u=new URL(a.href,location.href);
 if(u.pathname===path&&(!u.search||a.closest('.site-links')) || path.startsWith('/google-ledger/')&&u.pathname==='/google-ledger')a.setAttribute('aria-current','page')});
 try{nav.scrollTop=Number(sessionStorage.getItem('cost-nav-scroll')||0);
 const selected=new URLSearchParams(location.search).get('tab');
 if(selected)sessionStorage.setItem('cost-nav-trip',selected);
 const lastTrip=sessionStorage.getItem('cost-nav-trip');
 if(lastTrip)nav.querySelectorAll('a.nv[href]').forEach(a=>{const current=new URL(a.href).searchParams.get('tab')===lastTrip;
 a.classList.toggle('sel',current);if(current)a.setAttribute('aria-pressed','true');else a.removeAttribute('aria-pressed')});
 nav.addEventListener('scroll',()=>{try{sessionStorage.setItem('cost-nav-scroll',String(nav.scrollTop))}catch{}})}catch{}
})();
