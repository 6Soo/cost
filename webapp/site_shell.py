"""Shared server rendered application shell for private COST pages."""

from __future__ import annotations

import html
import re
from datetime import date
from urllib.parse import parse_qs, urlencode, urlsplit

from . import site_theme, ui_icons
from .site_assets import SHELL_STYLE as STYLE, SHELL_SCRIPT as SCRIPT

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

    pieces = re.split(r'(<script\b[^>]*>.*?</script\s*>)', document, flags=re.I | re.S)
    for index in range(0, len(pieces), 2):
        pieces[index] = re.sub(r'<p\b([^>]*)>(.*?)</p\s*>', paragraph, pieces[index], flags=re.I | re.S)
        pieces[index] = re.sub(r'<h3>행 편집 \(저장 준비 중\)</h3>', '', pieces[index])
        pieces[index] = re.sub(r'<button\b[^>]*\bdisabled[^>]*>저장 준비 중</button>', '', pieces[index])
    return ''.join(pieces)


def _query_dict(query):
    if isinstance(query, dict):
        return query
    return parse_qs(str(query or '').lstrip('?'), keep_blank_values=True)


def _first(value):
    return value[0] if isinstance(value, (list, tuple)) else (value or '')


def section_for(path: str, query='') -> str:
    parsed = urlsplit(path or '/')
    path = parsed.path or '/'
    q = _query_dict(query or parsed.query)
    tab = _first(q.get('tab'))
    if path == '/':
        return 'home'
    if path == '/receipts':
        return 'receipts'
    if path in ('/cards/all', '/ota', '/flight-passengers', '/rules'):
        return 'transactions'
    if path == '/board' and tab == 'refunds':
        return 'transactions'
    if path.startswith('/access/') or path == '/google-ledger' or path.startswith('/google-ledger/') or path == '/review':
        return 'admin'
    if path in ('/trips', '/board', '/export', '/expense/new', '/income/new', '/participants',
                '/participants/insurance-match', '/reserve-links'):
        return 'trips'
    return 'trips'


def _role():
    try:
        from . import ledger_board
        return ledger_board.current_role()
    except Exception:
        return 'owner'


def _esc(value):
    return html.escape(str(value or ''), quote=True)


def _request_tab(path, query):
    q = _query_dict(query)
    return _first(q.get('tab') or q.get('trip'))


def _trip(tab_id):
    if not tab_id or str(tab_id).startswith('quarter:'):
        return None
    try:
        from . import ledger_board
        return next((trip for trip in ledger_board.live_trips(include_archived=True)
                     if trip.get('tab_id') == tab_id), None)
    except Exception:
        return None


def _trip_label(tab_id):
    if str(tab_id or '').startswith('quarter:'):
        return '분기 기타비용'
    trip = _trip(tab_id)
    return str((trip or {}).get('display_title') or (trip or {}).get('display_key') or tab_id or '')


BRAND = '숲길여행 회계'
SPECIAL_TABS = {'refunds': '환불', 'unclassified': '미분류'}


def _screen_title(path, original, query, heading=''):
    path = urlsplit(path or '/').path or '/'
    q = _query_dict(query)
    tab = _first(q.get('tab'))
    defaults = {
        '/': '정산 현황', '/trips': '여행', '/cards/all': '거래', '/ota': '거래',
        '/receipts': '영수증', '/access/admin': '관리', '/google-ledger': 'Google 장부 연결',
        '/export': 'XLSX 내보내기', '/expense/new': '수기 지출 추가', '/income/new': '수입 직접 입력',
        '/participants': '참가자·보험', '/reserve-links': '예약 연결', '/rules': '거래',
        '/flight-passengers': '항공권 예약', '/board': '여행 장부',
    }
    # The visible h1 names the screen; the top bar and <title> must say the same.
    title = re.sub(r'\s*[·|｜-]\s*' + BRAND + r'\s*$', '', (heading or original or '').strip()).strip()
    if path == '/board' and tab and not heading:
        known = SPECIAL_TABS.get(tab) or (_trip_label(tab) if tab.startswith('quarter:') or _trip(tab) else '')
        title = known or defaults['/board']
    elif not title or title == BRAND or '웹 장부' in title or title.lower() in {'cost', 'synthetic shell', 'board'}:
        title = defaults.get(path, '여행 장부')
    return title


def _breadcrumb(path, query, title):
    path_name = urlsplit(path or '/').path or '/'
    q = _query_dict(query)
    tab = _first(q.get('trip') or q.get('tab'))
    trip = _trip(tab)
    trip_title = _trip_label(tab) if str(tab or '').startswith('quarter:') else str((trip or {}).get('display_title') or (trip or {}).get('display_key') or '')
    if path_name in ('/', '/trips'):
        return ''
    if path_name == '/board' and tab and trip_title:
        return ("<nav class='breadcrumb' aria-label='현재 위치'><ol>"
                "<li><a href='/trips'>여행</a></li><li>" + _esc(trip_title) +
                "</li><li aria-current='page'>장부</li></ol></nav>")
    if trip_title and path_name in {'/receipts', '/participants', '/participants/insurance-match',
                                    '/export', '/expense/new', '/income/new', '/reserve-links'}:
        return ("<nav class='breadcrumb' aria-label='현재 위치'><ol>"
                "<li><a href='/trips'>여행</a></li><li><a href='/board?" +
                _esc(urlencode({'tab': tab})) + "'>" + _esc(trip_title) + "</a></li><li aria-current='page'>" +
                _esc(title) + "</li></ol></nav>")
    return ''


def _active_trip_nav(tab_id, role='owner'):
    try:
        from . import ledger_board
        trips = ledger_board.live_trips(include_archived=True)
        if role == 'viewer':
            allowed = ledger_board.viewer_visible_tabs(ledger_board.current_request_session())
            trips = [trip for trip in trips if trip.get('tab_id') in allowed]
        trips = [trip for trip in trips if ledger_board.is_default_listed_trip(trip)]
    except Exception:
        trips = []
    trips = sorted(trips, key=lambda trip: (trip.get('starts_on') or '9999-99-99', trip.get('display_key') or ''))[:8]

    def short_date(value):
        bits = str(value or '').split('-')
        return f'{bits[1]}.{bits[2]}' if len(bits) == 3 and bits[0].isdigit() else str(value or '')

    links = []
    for trip in trips:
        tab = str(trip.get('tab_id') or '')
        label = str(trip.get('display_title') or trip.get('display_key') or tab)
        start, end = trip.get('starts_on') or '', trip.get('ends_on') or ''
        period = f'{short_date(start)}~{short_date(end)}' if start and end else short_date(start or end)
        current = tab == tab_id
        href = '/board?' + urlencode({'tab': tab})
        links.append("<li><a class='nv{}' href='{}'{}><span class='nv-icon'>{}</span><span class='nm'>{}</span><span class='ct'>{}</span></a></li>".format(
            ' nv-current' if current else '', _esc(href), " aria-current='page'" if current else '',
            ui_icons.icon('plane', 18), _esc(label), _esc(period)).replace('<a ', "<a title='" + _esc(label) + "' ", 1))
    if role == 'owner':
        quarter = (date.today().month - 1) // 3 + 1
        year = date.today().year
        quarter_tab = f'quarter:{year}:{quarter}'
        links.append("<li><a class='nv{}' href='/board?{}'{}><span class='nv-icon'>{}</span><span class='nm'>이번 분기 기타비용</span></a></li>".format(
            ' nv-current' if tab_id == quarter_tab else '', _esc(urlencode({'tab': quarter_tab})),
            " aria-current='page'" if tab_id == quarter_tab else '', ui_icons.icon('credit-card', 18)))
    if not links:
        links.append("<li class='muted'>진행 중인 여행이 없습니다.</li>")
    return "<div id='live-nav'><nav aria-label='진행 중 여행'><h2 class='nav-sec'>진행 중 여행</h2><ul class='nav-list'>{}</ul><a class='all-trips-link' href='/trips'>여행 전체 보기 {}</a></nav></div>".format(
        ''.join(links), ui_icons.icon('chevron-right', 16))


def sidebar(section='trips', tab_id='', role=None, live_nav=None):
    role = role or _role()
    owner = role != 'viewer'
    primary = ([('/', '홈', 'house', 'home'), ('/trips', '여행', 'plane', 'trips')]
               if owner else [('/trips', '여행', 'plane', 'trips')])
    if owner:
        primary += [('/cards/all', '거래', 'credit-card', 'transactions'),
                    ('/receipts', '영수증', 'receipt', 'receipts')]
    items = []
    for href, label, icon_name, key in primary:
        current = section == key
        current_attr = ' aria-current="page"' if current else ''
        items.append("<li><a href='{}' class='site-nav-link'{}>{}<span class='nm'>{}</span></a></li>".format(
            href, current_attr, ui_icons.icon(icon_name, 18), label))
    live = live_nav if live_nav is not None else _active_trip_nav(tab_id, role)
    manage = ''
    if owner:
        current = ' aria-current="page"' if section == 'admin' else ''
        manage = "<a class='nav-manage-link' href='/access/admin'{}>{}<span class='nm'>관리</span></a>".format(
            current, ui_icons.icon('users', 18))
    sidebar_bottom = ("<nav class='nav-bottom' aria-label='관리'><span class='nav-divider'></span>" + manage +
                      "</nav>") if owner else ""
    return ("<aside id=\"nav\" class='nav' aria-label='주 메뉴'><div class='nav-hd'>"
            "<a class='brand brand-link' href='/' aria-label='숲길여행 회계 홈으로 이동'>"
            "<img src='/assets/brand/wallet-favicon-v2.png' alt='' width='20' height='20'>숲길여행 회계</a></div>"
            "<nav class='site-links' aria-label='주 메뉴'><ul>" + ''.join(items) + "</ul></nav>"
            + live + sidebar_bottom + "</aside>")


def _topbar(title, back_href='', role='owner'):
    # The brand appears once; a screen name (also the h1) is shown only beside the back link.
    if back_href:
        lead = ("<a class='site-back' href='" + _esc(back_href) + "' aria-label='이전'>" + ui_icons.icon('chevron-left', 20) + "</a>"
                "<span class='site-topbar-title' title='" + _esc(title) + "'>" + _esc(title) + "</span>")
    else:
        lead = "<a class='site-brand-mobile' href='/' aria-label='" + BRAND + " 홈으로 이동'>" + BRAND + "</a>"
    theme = site_theme.BUTTON if role != 'viewer' else ''
    return '<header class="site-topbar">' + lead + theme + "</header>"


def _bottom_nav(section, role):
    if role == 'viewer':
        return ''
    links = [('/', '홈', 'house', 'home'), ('/trips', '여행', 'plane', 'trips'),
             ('/cards/all', '거래', 'credit-card', 'transactions'), ('/receipts', '영수증', 'receipt', 'receipts')]
    items = ''.join("<a href='{}'{}>{}<span>{}</span></a>".format(
        href, ' aria-current="page"' if section == key else '', ui_icons.icon(icon, 18), label)
        for href, label, icon, key in links)
    return ("<nav class='site-bottom-nav' aria-label='하단 메뉴'>" + items +
            "<button type='button' class='site-more-bottom site-more-toggle' aria-label='더보기' aria-haspopup='dialog' aria-controls='site-more-dialog'>" +
            ui_icons.icon('menu', 18) + '<span>더보기</span></button></nav>')


def _more_dialog(role, current_path=''):
    if role == 'viewer':
        return ''
    admin_current = " aria-current='page'" if current_path == '/access/admin' else ''
    return ("<dialog id='site-more-dialog' class='site-more-dialog' inert aria-labelledby='site-more-title'>"
            "<form method='dialog' class='site-more-close'><button class='icon-btn' value='close' aria-label='더보기 닫기'>" +
            ui_icons.icon('x-circle', 18) + "</button></form><h2 id='site-more-title'>더보기</h2>"
            "<div class='site-more-theme-slot' aria-label='화면 테마'></div>"
            "<nav aria-label='추가 메뉴'><a href='/access/admin'" + admin_current + ">계정·권한</a></nav></dialog>")


def app_shell(content, section='trips', title='', breadcrumb='', role=None, tab_id='', live_nav=None, back_href='', current_path=''):
    role = role or _role()
    return ("<a class='skip-link' href='#main'>본문으로 건너뛰기</a><div class='site-app'>" + sidebar(section, tab_id, role, live_nav) + "<div id=\"site-content\">" +
            _topbar(title, back_href, role) + (breadcrumb or '') + content +
            _bottom_nav(section, role) + _more_dialog(role, current_path) + "</div></div>")


MENU_TOGGLE = ''
TOPBAR_NAVIGATION = ''
BUTTON = site_theme.BUTTON


def _extract_body(document):
    opening = re.search(r'<body\b[^>]*>', document, re.I)
    closing = list(re.finditer(r'</body\s*>', document, re.I))
    if not opening or not closing:
        return '', '', ''
    content = document[opening.end():closing[-1].start()]
    content = re.sub(r'<aside\b[^>]*\bid=["\']nav["\'][^>]*>.*?</aside\s*>', '', content, count=1, flags=re.I | re.S)
    content = re.sub(r'<div\b[^>]*\bid=["\']nav-mask["\'][^>]*>.*?</div\s*>', '', content, count=1, flags=re.I | re.S)
    content = re.sub(r'<div\b[^>]*class=["\'][^"\']*\bapp\b[^"\']*["\'][^>]*>', '', content, count=1, flags=re.I)
    if re.search(r'</div>\s*$', content):
        content = re.sub(r'</div>\s*$', '', content, count=1)
    return content


def wrap_document(document, path, *, status=200):
    if 'data-trip-reservation-embed="1"' in document:
        return document
    if (status not in (200, 503) or 'id="site-shell-style"' in document
            or path.startswith(('/auth', '/login', '/demo', '/api/', '/health', '/ready'))):
        return document
    if status == 200:
        document = clean_static_help(document)
    body_match = re.search(r'<body\b[^>]*>', document, re.I)
    closing = list(re.finditer(r'</body\s*>', document, re.I))
    if not body_match or not closing:
        return document
    raw = _extract_body(document).strip()
    query = _query_dict(urlsplit(path).query)
    section = section_for(path, query)
    role = _role()
    title_match = re.search(r'<title\b[^>]*>(.*?)</title\s*>', document, re.I | re.S)
    original_title = html.unescape(re.sub(r'<[^>]*>', '', title_match.group(1))).strip() if title_match else ''
    h1_match = re.search(r'<h1\b[^>]*>(.*?)</h1\s*>', raw, re.I | re.S)
    heading = ' '.join(html.unescape(re.sub(r'<[^>]*>', '', h1_match.group(1))).split()) if h1_match else ''
    title = _screen_title(path, original_title, query, heading)
    tab_id = _request_tab(path, query)
    nav_tab_id = tab_id if urlsplit(path).path == '/board' else ''
    back_href = ''
    page_path = urlsplit(path).path
    if page_path == '/board':
        back_href = '/trips'
    elif section == 'trips' and page_path != '/trips':
        back_href = ('/board?' + urlencode({'tab': tab_id})) if tab_id else '/trips'
    elif section == 'transactions' and page_path not in ('/cards/all', '/ota'):
        back_href = '/cards/all'
    elif section == 'admin' and page_path != '/access/admin':
        back_href = '/access/admin'
    breadcrumb = _breadcrumb(path, query, title)
    try:
        from . import ledger_design
        live_nav = ledger_design.nav_region(nav_tab_id, '', '', '')
    except Exception:
        live_nav = None
    content = raw
    if not re.search(r'<main\b[^>]*\bid=["\']main["\']', content, re.I):
        own_main = re.search(r'<main\b([^>]*)>', content, re.I)
        if own_main and not re.search(r'\bid\s*=', own_main.group(1), re.I):
            content = re.sub(r'<main\b([^>]*)>', r"<main id='main'\1>", content, count=1, flags=re.I)
        else:
            # A page main with its own id keeps it (a second id attribute would be
            # ignored and drop every #page-id rule), so it becomes a div inside.
            if own_main:
                content = re.sub(r'<main\b', '<div', content, flags=re.I)
                content = re.sub(r'</main\s*>', '</div>', content, flags=re.I)
            content = "<main id='main' class='page'>" + content + '</main>'
    if not re.search(r'<h1\b', content, re.I):
        content = re.sub(r'(<main\b[^>]*>)', r'\1<h1>' + _esc(title) + '</h1>', content, count=1, flags=re.I)
    content = re.sub(r'<header\b[^>]*class=["\'][^"\']*site-topbar[^"\']*["\'][^>]*>.*?</header\s*>', '', content, flags=re.I | re.S)
    shell = app_shell(content, section, title, breadcrumb, role, nav_tab_id, live_nav, back_href, page_path)
    title_html = '<title>' + _esc(title) + ' · ' + BRAND + '</title>'
    if title_match:
        document = document[:title_match.start()] + title_html + document[title_match.end():]
    else:
        document = document.replace('</head>', title_html + '</head>', 1)
    if re.search(r'<html\b', document, re.I):
        def add_lang(match):
            attrs = match.group(1)
            return '<html' + (attrs if 'lang=' in attrs.lower() else attrs + ' lang="ko"') + '>'
        document = re.sub(r'<html\b([^>]*)>', add_lang, document, count=1, flags=re.I)
    body_match = re.search(r'<body\b[^>]*>', document, re.I)
    end = list(re.finditer(r'</body\s*>', document, re.I))[-1].start()
    return (document[:body_match.start()] + '<style id="site-shell-style">' + STYLE + site_theme.STYLE + '</style>'
            + '<script>' + site_theme.BOOTSTRAP + '</script><body class="site-shell-body">' + shell +
            '<script>' + SCRIPT + '</script>' + document[end:])
