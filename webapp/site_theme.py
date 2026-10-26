"""Browser-only theme choice for the shared private-page shell."""
from . import ui_icons

BUTTON = ('<div class="site-theme-bar"><button id="site-theme-toggle" type="button" '
          'aria-label="다크모드로 전환" title="다크모드로 전환">'
          '<span data-theme-icon="light">' + ui_icons.icon('sun') + '</span>'
          '<span data-theme-icon="dark">' + ui_icons.icon('moon') + '</span>'
          '</button></div>')

STYLE = """
:root{--shell-warn-bg:#FFF0E7;--shell-danger:#B42318}
@media(prefers-color-scheme:dark){:root{--shell-warn-bg:#332D20;--shell-danger:#FDA4AF}}
.site-theme-bar{display:flex;justify-content:flex-end;min-height:52px;padding:4px 12px;box-sizing:border-box;background:var(--shell-paper);flex:none}
#site-theme-toggle{display:inline-flex;align-items:center;justify-content:center;width:44px;min-width:44px;height:44px;min-height:44px;padding:0;margin:0;border:1px solid var(--shell-line-strong);border-radius:10px;background:var(--shell-paper);color:var(--shell-ink);cursor:pointer}
#site-theme-toggle:hover{background:var(--shell-hover)}
#site-theme-toggle:focus-visible{outline:2px solid var(--shell-focus);outline-offset:2px}
#site-theme-toggle .ic{width:22px;height:22px;display:block;pointer-events:none}
html[data-theme=dark] [data-theme-icon=light],html:not([data-theme=dark]) [data-theme-icon=dark]{display:none}
"""

# Runs after all head styles, before the body is displayed. Existing page-specific
# dark palettes (including non-token status styles) follow the same root state.
# The original media conditions are retained, so viewport/reduced-motion queries
# remain untouched. No requests or business-state mutations are performed.
BOOTSTRAP = """(()=>{
 const root=document.documentElement,key='cost-theme',system=matchMedia('(prefers-color-scheme:dark)');
 const valid=value=>value==='light'||value==='dark';
 let choice=null;try{const value=localStorage.getItem(key);if(valid(value))choice=value}catch{}
 const conditions=new Map();
 const collect=rules=>{for(const rule of rules){
   if(rule.media&&/prefers-color-scheme\\s*:\\s*(dark|light)/.test(rule.media.mediaText))conditions.set(rule,rule.media.mediaText);
   if(rule.cssRules)collect(rule.cssRules);
 }};
 for(const sheet of document.styleSheets){try{collect(sheet.cssRules)}catch{}}
 const apply=()=>{
   const theme=choice||(system.matches?'dark':'light');root.dataset.theme=theme;root.style.colorScheme=theme;
   for(const [rule,condition] of conditions){
     // Each color query is evaluated against the explicit effective theme.
     // Preserve any other comma-separated/combined media conditions.
     rule.media.mediaText=condition.replace(/\\(prefers-color-scheme\\s*:\\s*(dark|light)\\)/g,
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
})();"""
