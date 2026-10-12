"""Shared navigation for complete private HTML documents; fragments stay untouched."""
import re
from urllib.parse import parse_qs, urlsplit


STYLE = """
.site-topbar{display:none}.site-menu-toggle{font:inherit;min-height:44px;padding:8px 14px;cursor:pointer}
#nav a[aria-current=page]{background:#e5efe8;border-left:2px solid #24734b;font-weight:600}
#nav .site-links{display:grid;gap:4px;margin:0;padding:8px 12px}
#nav .site-links a{display:flex;align-items:center;min-height:40px;padding:8px;color:inherit;text-decoration:none;border-radius:6px}
body.site-standalone{margin:0!important;padding:0!important}
.site-app{min-height:100dvh;display:flex;min-width:0}
.site-app>#nav{position:fixed;inset:0 auto 0 0;width:232px;z-index:45;display:flex;flex-direction:column;
 overflow-y:auto;background:#f7f8f7;border-right:1px solid #e3e7e3;font:14px/1.5 system-ui;color:#202521}
.site-app>#nav *{box-sizing:border-box}
.site-app>#nav .nav-hd{padding:18px 16px 14px}.site-app>#nav .brand{font-size:15.5px;font-weight:700;margin:0}
.site-app>#nav .brand small{display:block;font-size:11.5px;font-weight:400;color:#657068}
.site-app>#nav .nav-q{display:block;margin:0 12px 6px;padding:0}
.site-app>#nav input{width:100%;min-height:40px;font:inherit;border:1px solid #d2d9d2;border-radius:6px;padding:8px}
.site-app>#nav .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
.site-app>#nav .work-menu{padding:12px;border:0;background:transparent;margin:0}
.site-app>#nav .work-menu h2,.site-app>#nav .nav-sec{font-size:12px;margin:10px 0;color:#657068}
.site-app>#nav .work-actions{display:grid;gap:4px;margin:0;padding:0}
.site-app>#nav .work-action{display:block;padding:8px;color:inherit;text-decoration:none;border-radius:6px;min-height:44px}
.site-app>#nav .work-action small{display:block;font-size:11px;color:#657068}
.site-app>#nav .nav-list{list-style:none;margin:0;padding:0 8px}
.site-app>#nav .nav-sec,.site-app>#nav .nav-ft{padding:8px 16px}
.site-app>#nav .nav-ft{font-size:11px;color:#657068}
.site-app>#nav .nv{display:flex;align-items:center;gap:6px;width:100%;min-height:40px;padding:8px;
 color:inherit;text-decoration:none;border:0;background:transparent;font:inherit;text-align:left}
.site-app>#nav .nm{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.site-app>#nav .ct{font-size:11px;white-space:nowrap;color:#657068}
.site-app>#nav .nv.sel{background:#e5efe8}.site-app>#nav a:hover{background:#edf1ed}
#site-content{margin-left:232px;width:calc(100% - 232px);min-width:0;padding:16px}
.site-app>.nav-mask[hidden]{display:none!important}
@media(max-width:759px){
 .site-topbar{display:flex;align-items:center;gap:12px;padding:6px 12px;background:#fff;border-bottom:1px solid #e3e7e3}
 .site-topbar button{width:auto!important;flex:none;color:#202521;background:white;border:1px solid #d2d9d2;border-radius:6px}
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
          'aria-label="전체 메뉴 열기" aria-controls="nav" aria-expanded="false">메뉴</button>'
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
