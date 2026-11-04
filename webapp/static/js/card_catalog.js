(()=>{
 const form=document.getElementById('card-filters');
 document.querySelectorAll('.card-catalog .header-button').forEach(button=>{
   const panel=document.getElementById(button.getAttribute('popovertarget'));
   const position=()=>{const r=button.getBoundingClientRect();
     panel.style.left=Math.max(12,Math.min(r.left,innerWidth-panel.offsetWidth-12))+'px';
     panel.style.top=Math.max(12,Math.min(r.bottom+6,innerHeight-panel.offsetHeight-12))+'px';};
   panel.addEventListener('beforetoggle',event=>{
     button.setAttribute('aria-expanded',String(event.newState==='open'));
   });
   panel.addEventListener('toggle',event=>{const open=event.newState==='open';
     button.setAttribute('aria-expanded',String(open));if(open)position();});
   window.addEventListener('resize',()=>{if(panel.matches(':popover-open'))position();});
 });
 document.querySelectorAll('.card-catalog .filter-option').forEach(button=>button.addEventListener('click',()=>{
   form.elements.namedItem(button.dataset.filter).value=button.dataset.value;
   form.requestSubmit();
 }));
})();
