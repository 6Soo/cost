"""Shared navigation for complete private HTML documents; fragments stay untouched."""
import re
import html
from urllib.parse import parse_qs, urlsplit

from . import ui_icons, site_theme


# 업무 화면의 고정 설명만 제거한다. 오류·보류·원본 값과 동의 문구는 건드리지 않는다.
EXPLANATION_PREFIXES = (
    '가맹점이 정확히 일치할 때 비용 항목을 적용합니다.',
    'Windows OCR로 사진의 글자를 읽습니다.',
    '자동 추출은 연결되지 않았습니다.',
    'iPhone 사진(HEIC 포함)이나 큰 사진은 업로드 전에 JPEG로 변환합니다.',
)


def clean_static_help(document):
    def paragraph(match):
        attrs, body = match.groups()
        if re.search(r'\brole\s*=|\bid\s*=', attrs, re.I):
            return match[0]
        plain = ' '.join(html.unescape(re.sub(r'<[^>]*>', '', body)).split())
        return '' if plain.startswith(EXPLANATION_PREFIXES) else match[0]
    # Keep scripts intact; they own mutations, confirmations and dynamic errors.
    pieces = re.split(r'(<script\b[^>]*>.*?</script\s*>)', document, flags=re.I | re.S)
    for index in range(0, len(pieces), 2):
        pieces[index] = re.sub(r'<p\b([^>]*)>(.*?)</p\s*>', paragraph, pieces[index], flags=re.I | re.S)
        pieces[index] = re.sub(r'<h3>행 편집 \(저장 준비 중\)</h3>', '', pieces[index])
        pieces[index] = re.sub(r'<button\b[^>]*\bdisabled[^>]*>저장 준비 중</button>', '', pieces[index])
    return ''.join(pieces)


STYLE = """
@font-face{font-family:"Pretendard Variable";src:url("/assets/fonts/PretendardVariable.woff2") format("woff2");font-weight:100 900;font-display:swap}
:root{--shell-bg:#F8FAFC;--shell-paper:#FFFFFF;--shell-ink:#0F172A;--shell-muted:#475569;--shell-warn:#B54708;--shell-line:#E2E8F0;--shell-line-strong:#D0D5DD;--shell-hover:#F8FAFC;--shell-selected:#ECF5EF;--shell-accent:#1C7A52;--shell-focus:#2266F5;--shell-overlay:rgba(16,24,40,.38)}
@media(prefers-color-scheme:dark){:root{--shell-bg:#0F172A;--shell-paper:#1E293B;--shell-ink:#F8FAFC;--shell-muted:#94A3B8;--shell-warn:#FBBF24;--shell-line:#334155;--shell-line-strong:#475569;--shell-hover:#334155;--shell-selected:#1E3A5F;--shell-accent:#34D399;--shell-focus:#93C5FD;--shell-overlay:rgba(0,0,0,.62)}}

/* Keep theme control inside the mobile navigation row, never above it. */
.site-topbar>.site-theme-bar{margin-left:auto;padding:0;min-height:0;display:flex;align-items:center;background:transparent}
.site-topbar #site-theme-toggle{width:40px!important;min-width:40px;height:40px;min-height:40px;padding:0!important}
@media(width < 760px){.site-topbar{width:100%;min-width:0;gap:10px}.site-topbar>span{flex:1 1 auto}.site-topbar>.site-theme-bar{flex:0 0 auto}}

.site-topbar{display:none}.site-menu-toggle{font:inherit;min-height:44px;padding:8px 14px;cursor:pointer;
 display:inline-flex;align-items:center;gap:8px}
.site-menu-toggle .ic,.catalog-btn .ic,.header-button .ic{width:16px;height:16px;flex:0 0 auto;pointer-events:none}
#nav .site-links a{display:flex;align-items:center;gap:8px}
#nav .site-links .nm{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#nav .nv .ic,#nav .work-action .ic{width:18px;height:18px;flex:0 0 auto;pointer-events:none}
#nav .nv .nv-icon{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;flex:0 0 20px;color:var(--shell-muted,#475569)}
#nav .nv .nv-icon .ic{width:18px;height:18px;display:block;flex:none}
#nav .nv.sel .nv-icon{color:var(--shell-accent,#1C7A52)}
#nav .work-action{display:flex;align-items:flex-start;gap:8px}
#nav .work-action>span{flex:1 1 auto;min-width:0}
#nav .btn .ic{width:16px;height:16px;flex:0 0 auto;pointer-events:none}
#nav .btn{transition:border-color .15s,background .15s}
@media(prefers-reduced-motion:reduce){
 #nav .btn,#nav .nv,.site-app>#nav{transition:none}
}
#nav{box-sizing:border-box;width:232px;flex:0 0 232px;min-height:0;margin:0;padding:0;display:flex;flex-direction:column;
 overflow:auto;background:var(--shell-bg,#F7F9FC);border-right:1px solid var(--shell-line,#E4E7EC);color:var(--shell-ink,#182230);
 font:400 14px/1.5 "Pretendard Variable","Pretendard",system-ui,-apple-system,"Segoe UI",Roboto,"Malgun Gothic",Apple SD Gothic Neo,sans-serif;
 word-break:keep-all;text-align:left}
#nav *{box-sizing:border-box}
#nav p{margin:0}#nav a{font:inherit;color:inherit;text-decoration:none}
#nav .nav-hd{padding:18px 16px 14px}
#nav .brand{font-size:15.5px;font-weight:700;letter-spacing:-.01em}
/* Quiet, intentional forest-green brand treatment across both themes. */
#nav a.brand.brand-link{background:var(--shell-selected,#ECF5EF);border:1px solid var(--shell-line,#E2E8F0);color:var(--shell-accent,#1C7A52);min-height:48px;padding:10px 12px;border-radius:11px;font-weight:750;transition:background-color .15s,border-color .15s}
#nav a.brand.brand-link:hover{background:var(--shell-hover,#F1F5F9);border-color:var(--shell-accent,#1C7A52)}
#nav a.brand.brand-link:focus-visible{outline:2px solid var(--shell-focus,#2266F5);outline-offset:3px}
/* Scrollbar belongs to the sidebar, not to every page's tables. */
#nav{scrollbar-width:thin;scrollbar-color:var(--shell-line-strong,#D0D5DD) transparent;scrollbar-gutter:stable}
#nav::-webkit-scrollbar{width:8px}
#nav::-webkit-scrollbar-track{background:transparent}
#nav::-webkit-scrollbar-thumb{background:var(--shell-line-strong,#D0D5DD);border:2px solid var(--shell-bg,#F8FAFC);border-radius:999px}
#nav::-webkit-scrollbar-thumb:hover{background:var(--shell-muted,#475569)}
#nav::-webkit-scrollbar-corner{background:transparent}
/* Low-noise utility footer pinned after the scrollable trip groups. */
#nav .nav-ft{display:grid;gap:7px;background:var(--shell-bg,#F8FAFC)}
#nav .nav-ft .all-trips-link{display:flex;align-items:center;justify-content:space-between;min-height:42px;padding:10px 12px;background:var(--shell-paper,#fff);border:1px solid var(--shell-line,#E2E8F0);border-radius:9px;color:var(--shell-ink,#0F172A);font-size:13px;font-weight:650}
#nav .nav-ft .all-trips-link:hover{border-color:var(--shell-accent,#1C7A52);background:var(--shell-hover,#F1F5F9)}
#nav .nav-ft .all-trips-link .ic{width:16px;height:16px;flex:0 0 auto;color:var(--shell-accent,#1C7A52)}
#nav .nav-ft .footer-help{margin:0;color:var(--shell-muted,#475569);font-size:11px;line-height:1.5}
@media(prefers-reduced-motion:reduce){#nav a.brand.brand-link{transition:none}}

#nav .brand small{display:block;font-size:11.5px;font-weight:400;color:var(--shell-muted,#667085);margin-top:3px}
#nav a.brand{display:block;color:inherit;text-decoration:none;border-radius:6px}
#nav a.brand:hover{background:var(--shell-hover,#F8FAFC)}
#nav a.brand:focus-visible{outline:2px solid var(--shell-focus,#2266F5);outline-offset:2px}
#nav a.brand.brand-link{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;text-align:center}
#nav a.brand.brand-link img{width:20px;height:20px;margin:0;flex:0 0 auto}
#nav .site-links{display:grid;gap:4px;margin:0;padding:8px 12px}
#nav .site-links a{display:flex;align-items:center;min-height:40px;padding:8px;border-radius:6px}
#nav .site-links a[href='/cards/all']{min-height:44px;border:1px solid transparent;border-radius:9px}
#nav .site-links a[href='/cards/all']:hover{border-color:var(--shell-line-strong,#D0D5DD);background:var(--shell-hover,#F8FAFC)}
#nav .site-links a[href='/cards/all'][aria-current=page]{border-color:var(--shell-accent,#1C7A52);background:var(--shell-selected,#ECF5EF);font-weight:750}
#nav a[aria-current=page]{background:var(--shell-selected,#ECF5EF);border-left:2px solid var(--shell-accent,#1C7A52);font-weight:600}
#nav .nav-q{display:block;margin:0 12px 6px;padding:0;border:0;background:transparent}
#nav .nav-q input{width:100%;height:32px;min-height:32px;max-width:100%;border:1px solid var(--shell-line-strong,#D0D5DD);
 border-radius:7px;background:var(--shell-paper,#fff);margin:0;padding:0 8px;font-family:inherit;font-size:13px;font-weight:400;line-height:1.5;color:inherit}
#nav .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
#nav .work-menu{padding:10px 12px;margin:0;border:0;border-radius:0;border-bottom:1px solid var(--shell-line,#E4E7EC);background:var(--shell-paper,#fff);flex:none}
#nav .work-menu h2{font-size:14px;font-weight:700;line-height:1.5;margin:0 0 8px;padding:0;color:var(--shell-ink,#182230)}
#nav .work-actions{display:grid;grid-template-columns:1fr;gap:8px;margin:0;padding:0}
#nav .work-action{display:block;flex:none;min-width:0;min-height:0;margin:0;padding:8px 10px;border:1px solid var(--shell-line,#E4E7EC);
 border-radius:8px;background:transparent;font-size:12px;font-weight:400;line-height:1.5;overflow-wrap:anywhere}
#nav .work-action strong{display:block}#nav .work-action small{display:none;font-size:12px;line-height:1.5;margin-top:3px;color:var(--shell-muted,#667085)}
#nav .nav-list{list-style:none;margin:0;padding:0 8px}
#nav .nav-sec{padding:12px 16px 6px;margin:0;font-size:11px;font-weight:600;line-height:1.5;color:var(--shell-muted,#667085);letter-spacing:.05em}
#nav .nav-ft{margin: auto 0 0;padding:12px 16px;border-top:1px solid var(--shell-line,#E4E7EC);font-size:11.5px;line-height:1.6;color:var(--shell-muted,#667085)}
#live-nav{display:flex;flex-direction:column;flex:1 0 auto}
#previous-trips{margin-top:auto;padding:12px 8px;border-top:1px solid var(--shell-line,#E4E7EC)}
#previous-trips>summary{cursor:pointer;min-height:44px;list-style:none}
#previous-trips[open]>summary>span:first-child{transform:rotate(90deg)}
#nav .nv{display:flex;align-items:center;gap:8px;width:100%;min-height:36px;padding:6px 8px;
 border:0;border-left:2px solid transparent;border-radius:7px;background:transparent;
 font-family:inherit;font-size:14px;line-height:1.5;font-weight:400;text-align:left;cursor:pointer;color:var(--shell-ink,#182230);text-decoration:none}
#nav .nm{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#nav .ct{flex:0 0 auto;margin-left:8px;font-size:12px;white-space:nowrap;color:var(--shell-muted,#667085)}
#nav .ct.warn{color:var(--shell-warn,#B54708)}
#nav .nv.sel,#nav .nv[aria-pressed=true]{background:var(--shell-selected,#ECF5EF);border-left-color:var(--shell-accent,#1C7A52);font-weight:600}
#nav a:hover{background:var(--shell-hover,#F8FAFC)}#nav .work-action:hover{border-color:var(--shell-accent,#1C7A52)}
#nav a:focus-visible,#nav button:focus-visible,#nav summary:focus-visible,#site-content :focus-visible{outline:2px solid var(--shell-focus,#2266F5);outline-offset:2px}
#nav .nav-toggle{margin:0 8px;max-width:calc(100% - 16px)}
#nav .nav-toggle[aria-expanded=true]{background:var(--shell-hover,#F8FAFC)}
#nav .arch-row{display:flex;align-items:center;gap:6px}#nav .arch-row .nv{flex:1 1 auto}
#nav .muted{color:var(--shell-muted,#667085);font-size:14px}
body.site-standalone{margin:0!important;padding:0!important}
.site-app{min-height:100dvh;display:flex;min-width:0}
.site-app>#nav{position:fixed;inset:0 auto 0 0;z-index:45}
#site-content{margin-left:232px;width:calc(100% - 232px);min-width:0;padding:16px}
.site-app>.nav-mask[hidden]{display:none!important}
@media(width < 760px){
 #nav{width:min(300px,85vw,100%);flex-basis:auto}
  #nav .nv{min-height:44px}#nav .nav-q input{font-size:16px}
  #nav a.brand{min-height:44px;display:flex;align-items:center}
 .site-topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;min-height:56px;box-sizing:border-box;padding:8px 16px;background:var(--shell-paper,#fff);border-bottom:1px solid var(--shell-line,#E4E7EC);box-shadow:0 1px 2px rgba(16,24,40,.04)}
 .site-topbar button{width:auto!important;flex:none;display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 14px;color:var(--shell-ink,#182230);background:var(--shell-paper,#fff);border:1px solid var(--shell-line-strong,#D0D5DD);border-radius:10px;font-size:14px;font-weight:600}
 .site-topbar>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:16px;font-weight:700;letter-spacing:-.01em;color:var(--shell-ink,#182230)}
 .site-app>#nav{width:min(300px,85vw);transform:translateX(-100%);transition:transform .18s ease}
 .site-app>#nav.open{transform:none}
 .site-app>.nav-mask{position:fixed;inset:0;background:var(--shell-overlay,rgba(16,24,40,.38));z-index:44}
 #site-content{margin-left:0;width:100%;padding:12px}
}
"""

SCRIPT = """(()=>{
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
          '<span>COST 업무 메뉴</span>' + site_theme.BUTTON + '</header>')


def wrap_document(document: str, path: str, *, status: int = 200) -> str:
    if (status not in (200, 503) or 'id="site-shell-style"' in document
            or path.startswith(('/auth', '/login', '/demo', '/api/', '/health', '/ready'))):
        return document
    if status == 200:
        document = clean_static_help(document)
    opening = re.search(r'<body\b[^>]*>', document, re.I)
    closing = list(re.finditer(r'</body\s*>', document, re.I))
    if not opening or not closing:
        return document
    end = closing[-1].start()
    content = document[opening.end():end]
    native = bool(re.search(r'\bid=[\"\']nav[\"\']', content))
    if native:
        content = re.sub(r'(<main\b[^>]*>)', lambda m: m[1] + site_theme.BUTTON, content, count=1)
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
    return (document[:opening.start()] + '<style id="site-shell-style">' + STYLE + site_theme.STYLE + '</style>'
            + '<script>' + site_theme.BOOTSTRAP + '</script>'
            + body + content + '<script>' + SCRIPT + '</script>' + document[end:])
