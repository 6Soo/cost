"""Shared navigation for complete private HTML documents; fragments stay untouched."""
import re
from urllib.parse import parse_qs, urlsplit

from . import ui_icons


STYLE = """
@font-face{font-family:"Pretendard Variable";src:url("/assets/fonts/PretendardVariable.woff2") format("woff2");font-weight:100 900;font-display:swap}
.site-topbar{display:none}.site-menu-toggle{font:inherit;min-height:44px;padding:8px 14px;cursor:pointer;
 display:inline-flex;align-items:center;gap:8px}
.site-menu-toggle .ic,.catalog-btn .ic,.header-button .ic{width:16px;height:16px;flex:0 0 auto;pointer-events:none}
#nav .site-links a{display:flex;align-items:center;gap:8px}
#nav .site-links .nm{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#nav .nv .ic,#nav .work-action .ic{width:18px;height:18px;flex:0 0 auto;pointer-events:none}
#nav .work-action{display:flex;align-items:flex-start;gap:8px}
#nav .work-action>span{flex:1 1 auto;min-width:0}
#nav .btn .ic{width:16px;height:16px;flex:0 0 auto;pointer-events:none}
#nav .btn{transition:border-color .15s,background .15s}
@media(prefers-reduced-motion:reduce){
 #nav .btn,#nav .nv,.site-app>#nav{transition:none}
}
#nav{box-sizing:border-box;width:232px;flex:0 0 232px;min-height:0;margin:0;padding:0;display:flex;flex-direction:column;
 overflow:auto;background:#F7F9FC;border-right:1px solid #E4E7EC;color:#182230;
 font:400 14px/1.5 "Pretendard Variable","Pretendard",system-ui,-apple-system,"Segoe UI",Roboto,"Malgun Gothic",Apple SD Gothic Neo,sans-serif;
 word-break:keep-all;text-align:left}
#nav *{box-sizing:border-box}
#nav p{margin:0}#nav a{font:inherit;color:inherit;text-decoration:none}
#nav .nav-hd{padding:18px 16px 14px}
#nav .brand{font-size:15.5px;font-weight:700;letter-spacing:-.01em}
#nav .brand small{display:block;font-size:11.5px;font-weight:400;color:#667085;margin-top:3px}
#nav a.brand{display:block;color:inherit;text-decoration:none;border-radius:6px}
#nav a.brand:hover{background:#F8FAFC}
#nav a.brand:focus-visible{outline:2px solid #2266F5;outline-offset:2px}
#nav .site-links{display:grid;gap:4px;margin:0;padding:8px 12px}
#nav .site-links a{display:flex;align-items:center;min-height:40px;padding:8px;border-radius:6px}
#nav a[aria-current=page]{background:#ECF5EF;border-left:2px solid #1C7A52;font-weight:600}
#nav .nav-q{display:block;margin:0 12px 6px;padding:0;border:0;background:transparent}
#nav .nav-q input{width:100%;height:32px;min-height:32px;max-width:100%;border:1px solid #D0D5DD;
 border-radius:7px;background:#fff;margin:0;padding:0 8px;font-family:inherit;font-size:13px;font-weight:400;line-height:1.5;color:inherit}
#nav .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
#nav .work-menu{padding:10px 12px;margin:0;border:0;border-radius:0;border-bottom:1px solid #E4E7EC;background:#fff;flex:none}
#nav .work-menu h2{font-size:14px;font-weight:700;line-height:1.5;margin:0 0 8px;padding:0;color:#182230}
#nav .work-actions{display:grid;grid-template-columns:1fr;gap:8px;margin:0;padding:0}
#nav .work-action{display:block;flex:none;min-width:0;min-height:0;margin:0;padding:8px 10px;border:1px solid #E4E7EC;
 border-radius:8px;background:transparent;font-size:12px;font-weight:400;line-height:1.5;overflow-wrap:anywhere}
#nav .work-action strong{display:block}#nav .work-action small{display:none;font-size:12px;line-height:1.5;margin-top:3px;color:#667085}
#nav .nav-list{list-style:none;margin:0;padding:0 8px}
#nav .nav-sec{padding:12px 16px 6px;margin:0;font-size:11px;font-weight:600;line-height:1.5;color:#667085;letter-spacing:.05em}
#nav .nav-ft{margin: auto 0 0;padding:12px 16px;border-top:1px solid #E4E7EC;font-size:11.5px;line-height:1.6;color:#667085}
#nav .nv{display:flex;align-items:center;gap:8px;width:100%;min-height:36px;padding:6px 8px;
 border:0;border-left:2px solid transparent;border-radius:7px;background:transparent;
 font-family:inherit;font-size:14px;line-height:1.5;font-weight:400;text-align:left;cursor:pointer;color:#182230;text-decoration:none}
#nav .nm{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#nav .ct{flex:0 0 auto;margin-left:8px;font-size:12px;white-space:nowrap;color:#667085}
#nav .ct.warn{color:#B54708}
#nav .nv.sel,#nav .nv[aria-pressed=true]{background:#ECF5EF;border-left-color:#1C7A52;font-weight:600}
#nav a:hover{background:#F8FAFC}#nav .work-action:hover{border-color:#1C7A52}
#nav .nav-toggle{margin:0 8px;max-width:calc(100% - 16px)}
#nav .nav-toggle[aria-expanded=true]{background:#F8FAFC}
#nav .arch-row{display:flex;align-items:center;gap:6px}#nav .arch-row .nv{flex:1 1 auto}
#nav .muted{color:#667085;font-size:14px}
body.site-standalone{margin:0!important;padding:0!important}
.site-app{min-height:100dvh;display:flex;min-width:0}
.site-app>#nav{position:fixed;inset:0 auto 0 0;z-index:45}
#site-content{margin-left:232px;width:calc(100% - 232px);min-width:0;padding:16px}
.site-app>.nav-mask[hidden]{display:none!important}
@media(max-width:759px){
 #nav{width:min(300px,85vw);flex-basis:auto}
  #nav .nv{min-height:44px}#nav .nav-q input{font-size:16px}
  #nav a.brand{min-height:44px;display:flex;align-items:center}
 .site-topbar{display:flex;align-items:center;gap:12px;padding:6px 12px;background:#fff;border-bottom:1px solid #E4E7EC}
 .site-topbar button{width:auto!important;flex:none;color:#182230;background:white;border:1px solid #D0D5DD;border-radius:8px}
 .site-app>#nav{width:min(300px,85vw);transform:translateX(-100%);transition:transform .18s ease}
 .site-app>#nav.open{transform:none}
 .site-app>.nav-mask{position:fixed;inset:0;background:rgba(16,24,40,.38);z-index:44}
 #site-content{margin-left:0;width:100%;padding:12px}
}
"""

SCRIPT = """(()=>{
 const nav=document.getElementById('nav'),mask=document.getElementById('nav-mask');if(!nav)return;
 const buttons=document.querySelectorAll('.site-menu-toggle,#btn-menu');
 const close=()=>{nav.classList.remove('open');if(mask)mask.hidden=true;buttons.forEach(b=>b.setAttribute('aria-expanded','false'))};
 buttons.forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();const open=!nav.classList.contains('open');
 nav.classList.toggle('open',open);if(mask)mask.hidden=!open;b.setAttribute('aria-expanded',String(open));
 if(open)nav.querySelector('a,input')?.focus()}));
 mask?.addEventListener('click',close);
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&nav.classList.contains('open')){close();buttons[0]?.focus()}});
 const path=location.pathname;
 nav.querySelectorAll('a[href]').forEach(a=>{const u=new URL(a.href,location.href);
 if(u.pathname===path&&!u.search || path.startsWith('/google-ledger/')&&u.pathname==='/google-ledger')a.setAttribute('aria-current','page')});
 try{nav.scrollTop=Number(sessionStorage.getItem('cost-nav-scroll')||0);
 const selected=new URLSearchParams(location.search).get('tab');
 if(selected)sessionStorage.setItem('cost-nav-trip',selected);
 const lastTrip=sessionStorage.getItem('cost-nav-trip');
 if(lastTrip)nav.querySelectorAll('a.nv[href]').forEach(a=>{const current=new URL(a.href).searchParams.get('tab')===lastTrip;
 a.classList.toggle('sel',current);if(current)a.setAttribute('aria-pressed','true');else a.removeAttribute('aria-pressed')});
 nav.addEventListener('scroll',()=>{try{sessionStorage.setItem('cost-nav-scroll',String(nav.scrollTop))}catch{}})}catch{}
})();"""

BUTTON = ('<header class="site-topbar"><button type="button" class="site-menu-toggle" '
          'aria-label="전체 메뉴 열기" aria-controls="nav" aria-expanded="false">'
          + ui_icons.icon("menu") +
          '메뉴</button>'
          '<span>COST 업무 메뉴</span></header>')


def wrap_document(document: str, path: str, *, status: int = 200) -> str:
    if (status not in (200, 503) or 'id="site-shell-style"' in document
            or path.startswith(('/auth', '/login', '/demo', '/api/', '/health', '/ready'))):
        return document
    opening = re.search(r'<body\b[^>]*>', document, re.I)
    closing = list(re.finditer(r'</body\s*>', document, re.I))
    if not opening or not closing:
        return document
    end = closing[-1].start()
    content = document[opening.end():end]
    native = bool(re.search(r'\bid=[\"\']nav[\"\']', content))
    if native:
        if not re.search(r'\bid=[\"\']btn-menu[\"\']', content):
            content = re.sub(r'(<main\b[^>]*>)', lambda m: m[1] + BUTTON, content, count=1)
        body = opening[0]
    else:
        from .ledger_design import _nav_html
        query = parse_qs(urlsplit(path).query)
        tab = (query.get('tab') or [''])[0]
        nav = _nav_html(tab, '')
        content = '<div class="site-app">' + nav + '<div id="site-content">' + BUTTON + content + '</div></div>'
        body = '<body class="site-standalone">'
    return (document[:opening.start()] + '<style id="site-shell-style">' + STYLE + '</style>'
            + body + content + '<script>' + SCRIPT + '</script>' + document[end:])
