"""Shared navigation for complete private HTML documents; fragments stay untouched."""
import re
import html
from urllib.parse import parse_qs, urlsplit

from . import ui_icons, site_theme
from .site_assets import SHELL_STYLE as STYLE, SHELL_SCRIPT as SCRIPT


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


MENU_TOGGLE = ('<button type="button" class="site-menu-toggle" '
               'aria-label="전체 메뉴 열기" aria-controls="nav" aria-expanded="false">'
               + ui_icons.icon("menu") +
               '메뉴</button>'
               '<span>COST 업무 메뉴</span>')

TOPBAR_NAVIGATION = '<header class="site-topbar">' + MENU_TOGGLE + '</header>'
BUTTON = '<header class="site-topbar">' + MENU_TOGGLE + site_theme.BUTTON + '</header>'


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
    title_match = re.search(r'<title\b[^>]*>(.*?)</title\s*>', document, re.I | re.S)
    title = html.escape(html.unescape(re.sub(r'<[^>]*>', '', title_match[1])).strip() if title_match else 'COST')
    topbar = BUTTON.replace('COST 업무 메뉴', title)
    native = bool(re.search(r'\bid=[\"\']nav[\"\']', content))
    if native:
        content = re.sub(r'(<main\b[^>]*>)', lambda m: m[1] + topbar, content, count=1)
        body = opening[0]
    else:
        from .ledger_design import _nav_html
        query = parse_qs(urlsplit(path).query)
        tab = (query.get('tab') or [''])[0]
        nav = _nav_html(tab, '')
        content = '<div class="site-app">' + nav + '<div id="site-content">' + topbar + content + '</div></div>'
        body = '<body class="site-standalone">'
    return (document[:opening.start()] + '<style id="site-shell-style">' + STYLE + site_theme.STYLE + '</style>'
            + '<script>' + site_theme.BOOTSTRAP + '</script>'
            + body + content + '<script>' + SCRIPT + '</script>' + document[end:])
