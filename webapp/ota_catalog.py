"""저장된 OTA 예약을 여행 배정 여부와 함께 읽기 전용으로 조회한다."""
import html
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode

from app import ota_payments, ota_portal, ota_sources
from . import ui_icons
from .card_catalog import CATALOG_SCRIPT, CATALOG_STYLE

PAGE_SIZE = 50
PROVIDERS = {'agoda': 'Agoda', 'trip': 'Trip.com', 'klook': 'Klook', 'booking': 'Booking.com'}
STATUSES = {'confirmed': '예약 확정', 'completed': '이용 완료', 'cancelled': '취소',
            'canceled': '취소', 'unknown': '미확인', 'observed': '수집됨'}
PRODUCTS = {'lodging': '숙박', 'flight': '항공', 'rental': '렌터카', 'package': '패키지', 'unknown': '미확인'}


def configured_sources(board):
    raw = os.environ.get('WEBLEDGER_OTA_SOURCES_JSON', '').strip()
    if raw:
        sources = json.loads(raw)
        if not isinstance(sources, dict):
            raise ValueError('invalid OTA sources')
        return sources
    root = Path(board.path).parent
    return ota_sources.resolve_sources(root,
        mail_default=os.environ.get('WEBLEDGER_OTA_MAIL_DIR') or root / 'ota-mail',
        portal_default=ota_portal.evidence_path(root))


def _database_rows(conn):
    """결제 근거가 부족한 예약도 제외하지 않는다. 원문·고객 정보는 읽지 않는다."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'bookings' not in tables:
        raise ValueError('not an OTA database')
    records = [dict(row) for row in conn.execute(
        'SELECT id,provider,booking_number,product_type,label,service_start_on,service_end_on,status FROM bookings')]
    links = {}
    if {'booking_target_links', 'allocation_targets'} <= tables:
        for row in conn.execute(
                "SELECT l.booking_id,t.code,t.name FROM booking_target_links l "
                "JOIN allocation_targets t ON t.id=l.target_id "
                "WHERE l.link_status IN ('confirmed','legacy') AND t.target_type='trip'"):
            links.setdefault(row[0], []).append({'id': row[1], 'name': row[2] or row[1]})
    return [{**row, 'trips': links.get(row['id'], [])} for row in records]


def _read_database(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    with closing(conn):
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        return _database_rows(conn)


def _saved_board_links(board, rows):
    """현재 저장된 장부 배정만 반영한다. 제공자 없는 예약번호가 모호하면 연결하지 않는다."""
    by_ref = {}
    for key in rows:
        by_ref.setdefault(key[1], []).append(key)
    with board._lock:
        saved = board.conn.execute(
            "SELECT r.display_tab_id,t.display_key,r.payload_json FROM board_rows r "
            "JOIN trip_tabs t ON t.tab_id=r.display_tab_id "
            "WHERE r.row_kind='expense' AND t.deleted=0 AND r.display_tab_id!='unclassified'").fetchall()
    for tab, name, payload in saved:
        try:
            record = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        ref = str(record.get('reservation_no') or record.get('booking_ref') or '').strip()
        evidence = record.get('ota_evidence') or {}
        provider = evidence.get('provider') if isinstance(evidence, dict) else None
        candidates = [(str(provider).lower(), ref)] if provider else by_ref.get(ref, [])
        if len(candidates) == 1 and candidates[0] in rows:
            rows[candidates[0]]['trips'].add((tab, name))


def catalog(board, query, *, sources=None):
    value = lambda key: str((query.get(key) or [''])[0]).strip()
    merged, warnings = {}, []

    def add(provider, ref, label='', start='', end='', status='', trips=()):
        provider, ref = str(provider or 'unknown').lower(), str(ref or '').strip()
        if not ref:
            return
        row = merged.setdefault((provider, ref), {'provider': provider, 'booking_ref': ref,
            'labels': set(), 'periods': set(), 'statuses': set(), 'trips': set()})
        if label:
            row['labels'].add(str(label))
        if start or end:
            row['periods'].add((str(start or ''), str(end or '')))
        if status:
            row['statuses'].add(str(status))
        row['trips'].update((str(t['id']), str(t['name'])) for t in trips)

    def add_database(records):
        for row in records:
            add(row['provider'], row['booking_number'], row['label'] or PRODUCTS.get(row['product_type'], row['product_type']),
                row['service_start_on'], row['service_end_on'], row['status'], row['trips'])

    try:
        sources = configured_sources(board) if sources is None else sources
    except (OSError, ValueError, ota_sources.OtaSourcesError):
        sources = {}
        warnings.append('OTA 자료 설정을 읽지 못했습니다. 관리자 설정을 확인해 주세요.')
    if sources.get('missing'):
        warnings.append('등록된 OTA 자료 중 찾을 수 없는 자료가 있습니다.')
    for path in dict.fromkeys(str(p) for p in sources.get('portal_databases', [])):
        if not Path(path).is_file():
            if str(path) in {str(p) for p in sources.get('registered', {}).get('portal_databases', [])}:
                warnings.append('등록된 OTA 예약 DB를 찾을 수 없습니다.')
            continue
        try:
            add_database(_read_database(path))
        except (OSError, ValueError, sqlite3.Error):
            warnings.append('일부 자료를 읽지 못했습니다. 예약 DB를 확인한 뒤 다시 조회해 주세요.')
    directories = [str(p) for p in dict.fromkeys(str(p) for p in sources.get('mail_directories', []))
                   if Path(p).is_dir()]
    events = []
    if directories:
        try:
            # 예약 목록에는 결제 이벤트 간 병합·대사가 필요하지 않다.
            # 모든 디렉터리를 함께 넘겨 기존 내용 해시 기반 파싱 캐시를 재사용한다.
            events = ota_payments._mail_events(directories)
        except (OSError, ValueError, ota_payments.OtaSourcesError):
            warnings.append('일부 자료를 읽지 못했습니다. OTA 메일 수집 상태를 확인해 주세요.')
            # 손상된 한 자료 때문에 다른 정상 디렉터리의 예약까지 숨기지 않는다.
            for directory in directories:
                try:
                    events.extend(ota_payments._mail_events([directory]))
                except (OSError, ValueError, ota_payments.OtaSourcesError):
                    continue
    for event in events:
        period = event.get('service_period') or {}
        if not isinstance(period, dict):
            period = {}
        add(event.get('provider'), event.get('booking_ref'), event.get('item'),
            period.get('starts_on'), period.get('ends_on'), event.get('reservation_status'))
    _saved_board_links(board, merged)
    rows = []
    for row in merged.values():
        periods = sorted(row.pop('periods'))
        rows.append({'provider': row['provider'], 'booking_ref': row['booking_ref'],
            'label': ' · '.join(sorted(row['labels'])),
            'starts_on': periods[0][0] if periods else '',
            'start_dates': [start for start, _ in periods if start],
            'period': ' / '.join(f'{start or "미확인"} ~ {end or "미확인"}' for start, end in periods),
            'status': ' / '.join(STATUSES.get(s, s) for s in sorted(row['statuses'])),
            'conflict': len(periods) > 1,
            'trips': [{'id': tab, 'name': name} for tab, name in sorted(row['trips'])]})
    all_count = len(rows)
    unassigned_count = sum(not row['trips'] for row in rows)
    months = sorted({day[:7] for r in rows for day in r['start_dates']
                     if re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)}, reverse=True)
    providers = sorted({r['provider'] for r in rows})
    month = value('month')
    if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', month):
        month = ''
    rows = [r for r in rows if (value('state') != 'unassigned' or not r['trips'])
        and (not value('provider') or r['provider'] == value('provider'))
        and (not month or any(day.startswith(month) for day in r['start_dates']))
        and (not value('q') or value('q').casefold() in ' '.join((r['booking_ref'], r['provider'],
            PROVIDERS.get(r['provider'], ''), r['label'], r['period'], *(t['name'] for t in r['trips']))).casefold())]
    known = sorted((r for r in rows if r['starts_on']),
        key=lambda r: (r['starts_on'], r['provider'], r['booking_ref']), reverse=value('sort') != 'asc')
    rows = known + sorted((r for r in rows if not r['starts_on']), key=lambda r: (r['provider'], r['booking_ref']))
    total = len(rows)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    try:
        page = min(pages, max(1, int(value('page') or '1')))
    except ValueError:
        page = 1
    return {'rows': rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], 'all_count': all_count,
            'unassigned_count': unassigned_count, 'total': total, 'page': page, 'pages': pages,
            'months': months, 'providers': providers, 'warnings': list(dict.fromkeys(warnings))}


def render_html(data, query):
    esc = lambda v: html.escape(str(v or ''), quote=True)
    value = lambda key: str((query.get(key) or [''])[0])

    def url(**changes):
        params = {k: value(k) for k in ('state', 'provider', 'q', 'month', 'sort') if value(k)}
        params.update(changes)
        return '/ota?' + urlencode(params)

    def choices(key, options, selected):
        return ''.join(f"<button type='button' class='filter-option' data-filter='{key}' data-value='{esc(k)}' "
            f"aria-pressed='{'true' if k == selected else 'false'}'>{esc(label)}</button>" for k, label in options)

    def heading(key, label, controls):
        return (f"<th class='has-filter'><button type='button' class='header-button' popovertarget='filter-{key}' "
            f"aria-label='{label}' aria-expanded='false' aria-controls='filter-{key}'>{label}{ui_icons.icon('chevron-down', 14)}</button>"
            f"<div id='filter-{key}' class='header-menu' popover aria-label='{label} 선택'>{controls}</div></th>")

    sort = 'asc' if value('sort') == 'asc' else 'desc'
    date_controls = choices('sort', [('desc', '내림차순 · 최근 이용 먼저'), ('asc', '오름차순 · 이른 이용 먼저')], sort)
    date_controls += choices('month', [('', '전체 월')] + [(m, m + '월') for m in data['months']], value('month'))
    provider_controls = choices('provider', [('', '모든 OTA')] + [(p, PROVIDERS.get(p, p)) for p in data['providers']], value('provider'))
    state_controls = choices('state', [('', '전체 내역'), ('unassigned', '여행 미배정')], value('state'))
    body = []
    for row in data['rows']:
        trips = ' · '.join(esc(t['name']) for t in row['trips']) or '여행 미배정'
        body.append('<tr>' + ''.join(f"<td data-label='{label}'>{text}</td>" for label, text in (
            ('이용일', esc(row['period'] or '미확인') + ('<br><strong>기간 확인 필요</strong>' if row['conflict'] else '')),
            ('OTA', esc(PROVIDERS.get(row['provider'], row['provider']))), ('예약번호', esc(row['booking_ref'])),
            ('예약 내용', esc(row['label'] or '미확인')), ('예약 상태', esc(row['status'] or '미확인')),
            ('여행 배정', trips))) + '</tr>')
    hidden = ''.join(f"<input type='hidden' name='{k}' value='{esc(value(k))}'>" for k in ('state', 'provider', 'month', 'sort'))
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        '<title>OTA 내역</title><style>' + CATALOG_STYLE +
        ".card-catalog td:before{display:none}@media(max-width:759px){.card-catalog td:before{display:block;content:attr(data-label);font-size:12px;color:#667085;margin-bottom:4px}}"
        '</style></head><body><main class="card-catalog"><h1>OTA 내역</h1>'
        '<p>저장된 예약 DB와 OTA 메일에서 예약을 모아 보여 줍니다. 같은 OTA의 같은 예약번호는 한 건입니다. '
        '여행 미배정은 저장된 예약·장부의 여행 연결이 없는 예약이며, 카드 결제 대사 여부와 다릅니다. 이 목록은 비용을 확정하지 않습니다.</p>'
        f"<nav class='catalog-actions' aria-label='OTA 내역 선택'><a class='catalog-btn{' primary' if value('state') != 'unassigned' else ''}' href='{esc(url(state='', page=1))}'>{ui_icons.icon('list')}OTA 전체 내역</a>"
        f"<a class='catalog-btn{' primary' if value('state') == 'unassigned' else ''}' href='{esc(url(state='unassigned', page=1))}'>{ui_icons.icon('map')}OTA 미배정 내역</a>"
        f"<a class='catalog-btn' href='/import#ota-review'>{ui_icons.icon('credit-card')}카드 대사·검토</a></nav>"
        f"<p id='card-count'>전체 {data['all_count']:,}건 · 여행 미배정 {data['unassigned_count']:,}건 · 검색 결과 {data['total']:,}건</p>"
        + ''.join(f"<p role='alert'>{esc(w)}</p>" for w in data['warnings'])
        + f"<form id='card-filters' action='/ota' method='get'><input name='q' aria-label='OTA 내역 검색' placeholder='예약번호·예약 내용·여행 검색' value='{esc(value('q'))}'>"
        f"<button class='catalog-btn primary' type='submit'>{ui_icons.icon('search')}검색</button><a class='catalog-btn' href='/ota'>초기화</a>{hidden}</form>"
        '<table><thead><tr>' + heading('date', '이용일', date_controls) + heading('provider', 'OTA', provider_controls)
        + '<th>예약번호</th><th>예약 내용</th><th>예약 상태</th>' + heading('state', '여행 배정', state_controls)
        + '</tr></thead><tbody>' + (''.join(body) or ('<tr><td colspan="6">조건에 맞는 OTA 예약이 없습니다.</td></tr>'
            if data['all_count'] else '<tr><td colspan="6">조회된 OTA 예약이 없습니다. 수집 자료 연결 상태를 확인해 주세요.</td></tr>'))
        + f"</tbody></table><nav class='catalog-pagination' aria-label='페이지 이동'><span>{data['page']} / {data['pages']} 페이지</span>"
        + (f"<a class='catalog-btn' href='{esc(url(page=data['page']-1))}'>이전</a>" if data['page'] > 1 else '')
        + (f"<a class='catalog-btn' href='{esc(url(page=data['page']+1))}'>다음</a>" if data['page'] < data['pages'] else '')
        + '</nav><script>' + CATALOG_SCRIPT + '</script></main></body></html>')


def dispatch(handler, parsed, *, board, is_owner, query):
    if parsed.path not in ('/ota', '/api/ota'):
        return False
    if not is_owner:
        handler._send_json({'code': 'NOT_FOUND'}, 404)
    elif board is None:
        handler._send_json({'code': 'STORE_UNBOUND'}, 503)
    else:
        data = catalog(board, query)
        if parsed.path == '/api/ota':
            handler._send_json(data)
        else:
            handler._send(render_html(data, query))
    return True
