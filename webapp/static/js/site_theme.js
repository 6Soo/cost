(()=>{
 const root=document.documentElement,key='cost-theme',system=matchMedia('(prefers-color-scheme:dark)');
 const valid=value=>value==='light'||value==='dark';
 let choice=null;try{const value=localStorage.getItem(key);if(valid(value))choice=value}catch{}
 const conditions=new Map();
 const collect=rules=>{for(const rule of rules){
   if(rule.media&&/prefers-color-scheme\s*:\s*(dark|light)/.test(rule.media.mediaText))conditions.set(rule,rule.media.mediaText);
   if(rule.cssRules)collect(rule.cssRules);
 }};
 for(const sheet of document.styleSheets){try{collect(sheet.cssRules)}catch{}}
 const apply=()=>{
   const theme=choice||(system.matches?'dark':'light');root.dataset.theme=theme;root.style.colorScheme=theme;
   for(const [rule,condition] of conditions){
     // Each color query is evaluated against the explicit effective theme.
     // Preserve any other comma-separated/combined media conditions.
     rule.media.mediaText=condition.replace(/\(prefers-color-scheme\s*:\s*(dark|light)\)/g,
       (_,value)=>value===theme?'(min-width:0px)':'(max-width:0px)');
   }
   const button=document.getElementById('site-theme-toggle');
   if(button){const label=theme==='dark'?'라이트모드로 전환':'다크모드로 전환';button.setAttribute('aria-label',label);button.title=label}
 };
 apply();
 document.addEventListener('DOMContentLoaded',()=>{apply();document.getElementById('site-theme-toggle')?.addEventListener('click',()=>{
   choice=root.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem(key,choice)}catch{}apply();
 })});
 system.addEventListener('change',()=>{if(!choice)apply()});
 addEventListener('storage',event=>{if(event.key===key||event.key===null){choice=valid(event.newValue)?event.newValue:null;apply()}});
})();