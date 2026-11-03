"""저장된 OTA 예약을 여행 배정 여부와 함께 조회하고, 예약마다 여행을 고르게 한다.

목록은 예약 색인을 한 번 만들어 두고 요청한 페이지만 그린다. 색인은 원본 자료와 장부가 바뀔 때만 다시 만든다.
예약 판단 화면은 카드 결제 근거, 여행 후보, 여행 일정 검증 결과를 함께 보여 준다. 배정은 검증된 여행에만
허용하며, 저장은 예약 배정 규칙(검토 저장소)으로 남기고 해당 카드 결제 원본만 다시 분류한다.
"""
import functools
import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import threading
import time
import zipfile
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from app import ota_payments, ota_portal, ota_sources
from app.reconciliation import covers_stay, handover_days, overlaps_stay, shared_days
from . import ui_icons
from .card_catalog import CATALOG_SCRIPT, CATALOG_STYLE

PAGE_SIZE = 50
PROVIDERS = {'agoda': 'Agoda', 'trip': 'Trip.com', 'klook': 'Klook', 'booking': 'Booking.com',
             'toyoko': '토요코인', 'forest': '숲나들e'}
STATUSES = {'confirmed': '예약 확정', 'completed': '이용 완료', 'cancelled': '취소',
            'canceled': '취소', 'unknown': '미확인', 'observed': '수집됨', 'upcoming': '예정'}
PRODUCTS = {'lodging': '숙박', 'flight': '항공', 'rental': '렌터카', 'package': '패키지', 'unknown': '미확인'}
#: Reservation statuses that mean the booking is real and may be placed by its stay dates alone.
#: Why a booking has no trip, in the words the owner reads. Each code is decided in _unassigned_reason.
UNASSIGNED_REASONS = {
    'cancelled': '취소된 예약',
    'revoked': '사용자가 배정을 해제함',
    'no_stay': '이용기간이 수집되지 않음',
    'tie': '같은 조건의 여행이 둘 이상이고 수입-비용 차액도 같음',
    'trip_unverified': '기간과 겹치는 여행의 일정 원본이 확인되지 않음',
    'no_trip': '기간과 겹치는 여행이 없음',
    'period_conflict': '이용기간 원본이 충돌함',
}
NOTICES = {
    'saved': '여행 배정을 저장했습니다. 카드 결제 원본은 다시 분류했습니다.',
    'revoked': '여행 배정을 해제했습니다. 카드 결제 원본은 다시 분류했습니다.',
}
ERROR_TEXT = {
    'BOOKING_CANCELLED': '취소된 예약은 여행에 배정하지 않습니다.',
    'NO_PERIOD': '이용기간이 없어 여행을 판단할 수 없습니다. 예약 메일을 먼저 확인해 주세요.',
    'TRIP_NOT_CANDIDATE': '이 예약 기간과 겹치지 않는 여행은 고를 수 없습니다.',
    'TRIP_NOT_VERIFIED': '이 여행의 일정 원본이 확인되지 않아 배정할 수 없습니다. 아래 사유를 확인해 주세요.',
    'PARTIAL_NEEDS_CONFIRM': '여행 기간과 예약 기간이 일부만 겹칩니다. 그래도 배정한다는 확인에 체크해 주세요.',
    'EXISTING_TRIP_DIFFERS': '이미 다른 여행에 연결된 예약입니다(예약 자료 또는 장부). 기존 연결을 먼저 정리해 주세요.',
    'REVIEW_STORE_UNCONFIGURED': '검토 자료 경로가 설정되지 않아 배정을 저장할 수 없습니다.',
    'REVISION_CONFLICT': '다른 곳에서 먼저 바꿨어요. 새로고침해 주세요.',
    'BASIS_REQUIRED': '배정 근거를 적어 주세요.',
    'BASIS_TOO_LONG': '배정 근거가 너무 깁니다.',
    'NO_ACTIVE_RULE': '해제할 배정이 없습니다.',
    'NOT_FOUND': '이 예약을 찾을 수 없습니다. 목록을 새로고침해 주세요.',
    'CSRF_REQUIRED': '화면을 새로 연 뒤 다시 시도해 주세요.',
    'INVALID_INPUT': '입력 내용을 확인해 주세요.',
    'REVIEW_UNAVAILABLE': '예약 근거 자료를 읽지 못해 분류를 다시 계산하지 못했습니다. 지출 정리에서 확인해 주세요.',
}

#: Bump when the index's shape changes, so a saved index from an older release is never read.
INDEX_VERSION = 5
INDEX_FILE = 'ota-catalog-index.json'
_INDEX = {'key': None, 'value': None}
_INDEX_LOCK = threading.Lock()
_INDEX_BUILD_LOCK = threading.Lock()
_SHEET_CACHE = {}


class _Refused(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


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
    if 'ota_store_meta' in tables:
        from app.ota_store import catalog_rows
        return catalog_rows(conn)
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
            rows[candidates[0]]['ledger_trips'].add((tab, name))


def _day(value):
    text = str(value or '')[:10]
    return text if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text) else ''


def _stay(periods):
    """First start and last end of the listed service periods, or None when no date is known."""
    starts = [_day(start) for start, _ in periods if _day(start)]
    ends = [_day(end) for _, end in periods if _day(end)]
    if not starts or not ends:
        return None
    return min(starts), max(ends)


def _relation(stay, trip, *, service=False, handover=()):
    """How a booking's stay sits on a trip: covered, partly overlapping, or apart. A flight counts both days."""
    if not stay or not trip['starts_on'] or not trip['ends_on']:
        return 'none'
    start, end = stay
    if covers_stay(trip['starts_on'], trip['ends_on'], start, end, service=service, handover=handover):
        return 'covers'
    if overlaps_stay(trip['starts_on'], trip['ends_on'], start, end, service=service, handover=handover):
        return 'overlaps'
    return 'none'


def _automatic_trip(trips, stay, *, service=False, nets=None):
    """Read-only assignment: existing verified trips only; ambiguous choices stay visibly inferred."""
    if not stay:
        return None
    valid = [t for t in trips if t['valid'] and t['starts_on'] and t['ends_on']]
    handover = handover_days(valid)
    pool = [t for t in valid if _relation(stay, t, service=service, handover=handover) != 'none']
    preparation = not pool
    if preparation:
        if service:
            return None
        # The existing preparation-stay contract needs ALL trips, not just overlaps.
        pool = [t for t in valid if t['starts_on'] >= stay[1]]
        if not pool:
            return None
        first = min(t['starts_on'] for t in pool)
        pool = [t for t in pool if t['starts_on'] == first]
    if nets is None:
        from .card_flow import _google_nets
        nets = _google_nets()
    def rank(t):
        return (covers_stay(t['starts_on'], t['ends_on'], *stay, service=service, handover=handover),
                shared_days(t['starts_on'], t['ends_on'], *stay, service=service, handover=handover),
                nets.get(t['tab_id'], float('-inf')), t['starts_on'] == stay[0],
                t['starts_on'], t['ends_on'])
    pool.sort(key=lambda t: (rank(t), t['tab_id']), reverse=True)
    chosen = pool[0]
    ambiguous = len(pool) > 1 and rank(pool[0]) == rank(pool[1])
    basis = ('준비 숙박 · 체크아웃 이후 가장 가까운 여행' if preparation else
             '이용기간 포함·겹치는 일수·수입-비용 차액·여행 시작일 순으로 선택')
    if ambiguous:
        basis += ' · 동률 후보 중 고정 순서로 우선 배정'
    if preparation:
        gap = (date.fromisoformat(chosen['starts_on']) - date.fromisoformat(stay[1])).days
        basis += f' · 체크아웃부터 여행 시작까지 {gap}일'
    return {'id': chosen['tab_id'], 'name': chosen['name'], 'source': 'period',
            'assignment_state': 'AUTO_INFERRED', 'confidence': '낮음' if preparation or ambiguous else '보통',
            'basis': basis, 'preparation': preparation}


def _sheet_titles(path):
    """Sheet names in an xlsx workbook, or None when the file cannot be read."""
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read('xl/workbook.xml').decode('utf-8')
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError):
        return None
    return {html.unescape(name) for name in re.findall(r'<(?:\w+:)?sheet\b[^>]*\bname="([^"]*)"', xml)}


def _trip_reason(trip_code):
    """Why a trip's schedule cannot be verified against the current source. Plain text for the owner."""
    from . import real_review
    from .card_flow import _trip_authority
    path = os.environ.get('WEBLEDGER_TRIP_AUTHORITY')
    if not path:
        return '여행 일정 원본 설정이 없습니다'
    try:
        records, _ = _trip_authority(Path(path))
    except (OSError, ValueError, KeyError, TypeError):
        return '여행 일정 원본 기록을 읽지 못했습니다'
    matches = [record for record in records if record.trip_code == trip_code]
    if not matches:
        return '여행 일정 원본 기록이 없습니다'
    record = matches[0]
    if not record.source_locator.partition('#')[0].lower().endswith('.xlsx'):
        return '예약 명단 또는 소유자 일정 근거가 바뀌었습니다'
    service = real_review.active_service()
    if service is None:
        return '여행 일정 원본 자료가 등록되지 않았습니다'
    snapshot = Path(service.manifest['snapshot_path'])
    key = (str(snapshot), snapshot.stat().st_size if snapshot.exists() else -1)
    if key not in _SHEET_CACHE:
        _SHEET_CACHE.clear()
        _SHEET_CACHE[key] = _sheet_titles(snapshot)
    titles = _SHEET_CACHE[key]
    if titles is None:
        return '현재 일정 원본을 읽지 못했습니다'
    if trip_code not in titles:
        return f"현재 일정 원본에 '{trip_code}' 시트가 없습니다. 원본이 바뀌었습니다"
    return '현재 일정 원본과 맞지 않습니다. 시트 제목과 일정 칸을 다시 확인해야 합니다'


def _trip_context(board, flow):
    """Active trips with their verification result. Verified once per index build."""
    trips = []
    for trip in board.list_trips():
        try:
            valid = bool(flow.trip_valid(trip['tab_id']))
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            valid = False
        reason = '' if valid else _trip_reason(trip['display_key'])
        trips.append({'tab_id': trip['tab_id'], 'name': trip['display_key'], 'destination': trip.get('destination') or '',
                      'starts_on': _day(trip.get('starts_on')), 'ends_on': _day(trip.get('ends_on')),
                      'valid': valid, 'reason': reason})
    return trips


def _card_matches(flow):
    """Live card payments per booking, from the reconciliation the card review already uses."""
    from . import ota_payment_review
    current = None
    try:
        if ota_payment_review.enabled():
            current, fresh = ota_payment_review.snapshot_service(flow.board).held()
            if current is None or not fresh:
                # A read must not run the legacy fallback while the worker is
                # refreshing canonical evidence. Keep the state visibly pending.
                return {}, {}, True
            report = flow._canonical_snapshot_report(current)
        else:
            report = flow._ota_report()
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return {}, {}, True
    facts = list((report or {}).get('matches', []))
    pending = False
    if current is not None:
        facts = _with_core_card_matches(facts, current.get('data') or {})
    live, cancelled = defaultdict(list), defaultdict(int)
    for fact in facts:
        key = (str(fact.get('provider') or '').lower(), str(fact.get('booking_ref') or ''))
        if fact.get('reservation_status') == 'cancelled':
            cancelled[key] += 1
            continue
        live[key].append({'transaction_id': str(fact.get('transaction_id') or ''),
                          'source_hash': str(fact.get('source_hash') or ''),
                          'merchant': str(fact.get('merchant') or ''),
                          'paid_on': str(fact.get('paid_on') or ''),
                          'paid_amount_krw': fact.get('paid_amount_krw'),
                          'item': str(fact.get('item') or ''),
                          'direction': str(fact.get('direction') or 'purchase'),
                          'period_conflict': bool(fact.get('period_conflict'))})
        live[key][-1]['inferred_link'] = bool(fact.get('inferred_link'))
        live[key][-1]['allocation_basis'] = fact.get('allocation_basis')
    return dict(live), dict(cancelled), pending


def _with_core_card_matches(facts, data):
    from app.ota_core_projection import card_matches
    return card_matches(facts, data)


def _reservation_card_candidates(flow):
    """같은 중앙 스냅샷의 예약 후보를 확정 카드 연결과 분리해 표시한다."""
    from . import ota_payment_review
    if not ota_payment_review.enabled():
        return {}
    current, fresh = flow._held_ota_snapshot()
    if not current or not fresh:
        return {}
    data = current.get('data') or {}
    events = {e['ota_event_id']: e for e in data.get('events', ())}
    found = defaultdict(set)
    for result in data.get('results', ()):
        event = events.get(result.get('ota_event_id')) or {}
        trace = result.get('candidate_search') or {}
        if not trace.get('reservation_only'):
            continue
        for candidate in trace.get('candidates') or ():
            found[(event['provider'], _catalog_reference(event))].add(candidate['transaction_id'])
    return {key: sorted(ids) for key, ids in found.items()}


def _reservation_link_states(flow):
    """저장·추론 예약 관계를 결제 대사 결과와 별도 표시한다."""
    from . import ota_payment_review
    if not ota_payment_review.enabled():
        return {}
    current, fresh = flow._held_ota_snapshot()
    if not current or not fresh:
        return {}
    events = {str(event.get('ota_event_id')): event for event in (current.get('data') or {}).get('events', ())}
    cards = {str(card.get('transaction_id') or ''): card
             for card in (current.get('data') or {}).get('transactions', ())}
    states = defaultdict(list)
    for result in (current.get('data') or {}).get('results', ()):
        relation = result.get('reservation_link') or {}
        if relation.get('status') not in ('INFERRED', 'USER_CONFIRMED', 'NEEDS_REVIEW', 'STALE'):
            continue
        event = events.get(str(result.get('ota_event_id') or ''), {})
        key = (str(event.get('provider') or ''), str(_catalog_reference(event) or ''))
        card = cards.get(str(relation.get('transaction_id') or ''), {})
        states[key].append({'status': relation.get('status'),
                            'merchant': card.get('merchant') or card.get('issuer') or '',
                            'day': card.get('approval_date') or card.get('posting_date') or '',
                            'amount_krw': card.get('amount_krw'),
                            'amount_status': relation.get('amount_status')})
    return {key: sorted(values, key=lambda value: (value.get('status') or '', value.get('merchant') or ''))
            for key, values in states.items()}


def _payment_link_states(flow):
    from . import ota_payment_review
    from app.ota_payment_relations import catalog_links
    if not ota_payment_review.enabled():
        return {}
    current, fresh = flow._held_ota_snapshot()
    return catalog_links(current.get('data') or {}) if current and fresh else {}


def _review_store():
    """The OTA review store for reads, or None when isolated review is not configured or has no file yet."""
    from . import ota_payment_review
    from app.ota_review import OtaReviewStore
    path = ota_payment_review.review_db_path()
    if not ota_payment_review.enabled() or not path or not Path(path).is_file():
        return None
    try:
        return OtaReviewStore(path)
    except ValueError:
        return None


def _owner_rule_states():
    """Each booking's owner trip rule, active or revoked, keyed by (provider, booking_ref)."""
    store = _review_store()
    if store is None:
        return {}
    try:
        return store.booking_trip_states()
    finally:
        store.close()


def _unassigned_reason(entry, revoked):
    """The first reason a booking has no trip, or None when it has one. Plain codes; the text is UNASSIGNED_REASONS."""
    if entry['trips']:
        return None
    codes = set(entry['status_codes'])
    if 'cancelled' in codes:
        return 'cancelled'
    if revoked:
        return 'revoked'
    if entry.get('conflict'):
        return 'period_conflict'
    if not entry['stay']:
        return 'no_stay'
    if any(c['valid'] for c in entry['candidates']):
        return 'tie'
    if entry['candidates']:
        return 'trip_unverified'
    return 'no_trip'


def _canonical(value):
    """A JSON-ready form whose text does not depend on set order or hash seed, so a saved key matches next run."""
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return str(value) if isinstance(value, Path) else value


#: The modules whose logic decides the index. A saved index made by other code is never read.
_LOGIC_FILES = ('webapp/ota_catalog.py', 'webapp/ota_catalog_sources_child.py', 'webapp/card_flow.py', 'webapp/ota_payment_review.py', 'app/ota_mail.py', 'app/ota_payments.py', 'app/forest_mail.py',
                'app/ota_booking_context.py', 'app/ota_core_projection.py', 'app/toyoko_mail.py', 'app/airline_payment_mail.py',
                'app/ota_inference.py',
                'app/classify.py', 'app/rules.py', 'app/reconciliation.py', 'app/ota_portal.py', 'app/ota_exact.py',
                'app/ota_sources.py', 'app/ota_store.py', 'app/booking_evidence.py', 'app/ota_matching_defaults.py',
                'config/ota-matching-defaults.json')


@functools.lru_cache(maxsize=None)
def _code_stamp():
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent.parent
    for rel in _LOGIC_FILES:
        digest.update(rel.encode())
        path = root / rel
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _signature(board, sources):
    """Everything the index reads. Any change here rebuilds the index; nothing else does."""
    from .card_flow import CardFlow
    CardFlow(board)  # creates the card tables on a fresh board, so they are part of the first signature
    parts = [INDEX_VERSION, _code_stamp(), hashlib.sha256(json.dumps(_canonical(sources), ensure_ascii=False).encode()).hexdigest()]
    from . import ota_payment_review
    if ota_payment_review.enabled():
        current, fresh = ota_payment_review.snapshot_service(board).held()
        parts.append(('core', (current or {}).get('key'), (current or {}).get('generation'), fresh))

    def stat_key(path):
        try:
            info = Path(path).stat()
            return (str(path), info.st_size, info.st_mtime_ns)
        except OSError:
            return (str(path), -1, -1)

    for path in dict.fromkeys(str(p) for p in sources.get('portal_databases', [])):
        # SQLite's -shm is a disposable shared-memory index. Reading a WAL database
        # can rewrite it without changing a booking, causing endless rebuilds.
        parts += [stat_key(path), stat_key(path + '-wal')]
    for directory in dict.fromkeys(str(p) for p in sources.get('mail_directories', [])):
        if Path(directory).is_dir():
            parts += [stat_key(p) for p in sorted(Path(directory).glob('*.json'))]
    parts += [stat_key(p) for p in sources.get('reference_documents', [])]
    authority = os.environ.get('WEBLEDGER_TRIP_AUTHORITY')
    if authority:
        parts.append(stat_key(authority))
    review_db = os.environ.get('WEBLEDGER_OTA_REVIEW_DB', '').strip()
    if review_db:
        parts += [stat_key(review_db), stat_key(review_db + '-wal')]
    config = os.environ.get('WEBLEDGER_REVIEW_CONFIG', '').strip()
    if config:
        parts.append(stat_key(config))
    google = os.environ.get('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', '').strip()
    if google:
        # 여행 검증이 구글 탭 기간과 탭 연결을 읽는다.
        parts += [stat_key(google), stat_key(Path(google).with_name('google-tab-mapping.json'))]
    with board._lock:
        for query in (
                "SELECT transaction_id,source_hash,merchant,approval_date,posting_date,amount_krw,"
                "transaction_direction,duplicate_of,conflict_reason,parse_error,classification_state,"
                "display_tab_id,revision,decided_at FROM transactions ORDER BY transaction_id",
                "SELECT row_id,display_tab_id,payload_json FROM board_rows WHERE row_kind='expense' ORDER BY row_id",
                "SELECT tab_id,display_key,starts_on,ends_on,deleted,archived,revision FROM trip_tabs ORDER BY tab_id"):
            try:
                parts.append(hashlib.sha256(json.dumps(board.conn.execute(query).fetchall(),
                                                       default=str).encode()).hexdigest())
            except sqlite3.OperationalError:
                parts.append('missing')
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


def _catalog_reference(event):
    from app.forest_mail import catalog_reference
    return catalog_reference(event)


def _rows_from_sources(board, sources, warnings):
    merged = {}
    invalid_provider_bookings = set()

    def add(provider, ref, label='', start='', end='', status='', trips=(), *,
            identity_kind='supplier_booking', supplier_booking_ref=None):
        provider, ref = str(provider or 'unknown').lower(), str(ref or '').strip()
        if not ref:
            return
        # 오래된 참고 DB에 'Gmail Trip.com 예약 ...'처럼 자료 제목이 공급자로
        # 들어간 행이 있다. 예약번호가 같더라도 독립적인 결제/일정 근거가 아니므로
        # 정상 Trip 예약과 병합하거나 별개 OTA 예약으로 자동 배정하지 않는다.
        if provider not in PROVIDERS and provider != 'unknown':
            invalid_provider_bookings.add((provider, ref))
            return
        row = merged.setdefault((provider, ref), {'provider': provider, 'booking_ref': ref,
            'identity_kind': identity_kind,
            'supplier_booking_ref': supplier_booking_ref if identity_kind=='reservation_observation' else ref,
            'labels': set(), 'periods': set(), 'statuses': set(), 'portal_trips': set(), 'ledger_trips': set()})
        if label:
            row['labels'].add(str(label))
        if start or end:
            row['periods'].add((str(start or ''), str(end or '')))
        if status:
            row['statuses'].add(str(status))
        row['portal_trips'].update((str(t['id']), str(t['name'])) for t in trips)

    def add_database(records):
        for row in records:
            add(row['provider'], row['booking_number'], row['label'] or PRODUCTS.get(row['product_type'], row['product_type']),
                row['service_start_on'], row['service_end_on'], row['status'], row['trips'],
                identity_kind=row.get('identity_kind','supplier_booking'),
                supplier_booking_ref=row.get('supplier_booking_ref'))

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
                   if Path(p).is_dir() or Path(p).is_file()]
    events = []
    if directories:
        try:
            # 예약 목록에는 결제 이벤트 간 병합·대사가 필요하지 않다.
            # 모든 디렉터리를 함께 넘겨 기존 내용 해시 기반 파싱 캐시를 재사용한다.
            events = ota_payments._mail_events(directories, read_only=True)
        except (OSError, ValueError, ota_payments.OtaSourcesError):
            warnings.append('일부 자료를 읽지 못했습니다. OTA 메일 수집 상태를 확인해 주세요.')
            # 손상된 한 자료 때문에 다른 정상 디렉터리의 예약까지 숨기지 않는다.
            for directory in directories:
                try:
                    events.extend(ota_payments._mail_events([directory], read_only=True))
                except (OSError, ValueError, ota_payments.OtaSourcesError):
                    continue
    for event in events:
        period = event.get('service_period') or {}
        if not isinstance(period, dict):
            period = {}
        observed = event.get('provider')=='forest' and event.get('event_type')=='reservation'
        add(event.get('provider'), _catalog_reference(event), event.get('item'),
            period.get('starts_on'), period.get('ends_on'), event.get('reservation_status'),
            identity_kind='reservation_observation' if observed else 'supplier_booking',
            supplier_booking_ref=event.get('booking_ref'))
    if invalid_provider_bookings:
        warnings.append(f'공급자 표기가 잘못된 예약 {len(invalid_provider_bookings)}건은 자동 배정에서 보류했습니다.')
    _join_by_booking_number(merged)
    _saved_board_links(board, merged)
    return merged


def _join_by_booking_number(rows):
    """A confirmation whose provider is unknown is the same booking as the payment with its number, when only one exists."""
    named = {}
    for provider, ref in rows:
        if provider != 'unknown':
            named.setdefault(ref, []).append((provider, ref))
    for key in [k for k in rows if k[0] == 'unknown']:
        targets = named.get(key[1], [])
        if len(targets) != 1:
            continue
        source = rows.pop(key)
        target = rows[targets[0]]
        for field in ('labels', 'periods', 'statuses', 'portal_trips', 'ledger_trips'):
            target[field].update(source[field])


def _source_rows_in_child(board, sources, warnings):
    """Parse large mail bundles outside the HTTP process's interpreter lock."""
    import pickle
    import subprocess
    import sys
    import tempfile
    root = str(Path(__file__).resolve().parents[1])
    bootstrap = ('import sys; sys.path.insert(0, sys.argv[1]); '
                 'from webapp import ota_catalog_sources_child as child; child.run(*sys.argv[2:])')
    with tempfile.TemporaryDirectory(prefix='ota-catalog-worker-', dir=Path(board.path).parent) as directory:
        request, result = Path(directory) / 'request', Path(directory) / 'result'
        request.write_bytes(pickle.dumps(sources, protocol=pickle.HIGHEST_PROTOCOL))
        process = subprocess.Popen(
            [sys.executable, '-I', '-c', bootstrap, root, str(board.path), str(request), str(result)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            process.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            from .ota_payment_review import _stop_process_tree
            _stop_process_tree(process.pid)
            process.wait()
            raise RuntimeError('OTA_CATALOG_SOURCE_TIMEOUT') from None
        if process.returncode or not result.exists():
            raise RuntimeError('OTA_CATALOG_SOURCE_WORKER_FAILED')
        payload = pickle.loads(result.read_bytes())
        if payload[0] != 'ok':
            raise RuntimeError('OTA_CATALOG_SOURCE_WORKER_FAILED:' + payload[1])
        warnings.extend(payload[2])
        return payload[1]


def _build_index(board, sources):
    from .card_flow import CardFlow
    from .history_policy import preserved_periods
    warnings = []
    merged = (_source_rows_in_child(board, sources, warnings)
              if getattr(board, '_catalog_source_process', False)
              else _rows_from_sources(board, sources, warnings))
    flow = CardFlow(board)
    trips = _trip_context(board, flow)
    trip_by_id = {trip['tab_id']: trip for trip in trips}
    live, cancelled, card_error = _card_matches(flow)
    reservation_candidates = _reservation_card_candidates(flow)
    reservation_links = _reservation_link_states(flow)
    payment_links = _payment_link_states(flow)
    if card_error:
        warnings.append('카드 결제와 예약을 대조하지 못했습니다. 지출 정리에서 자료를 확인해 주세요.')
    states = _owner_rule_states()
    rules = {key: rule for key, rule in states.items() if rule['status'] == 'active'}
    entries = []
    handover = handover_days(trips)
    from .card_flow import _google_nets
    nets = _google_nets()
    for row in merged.values():
        periods = sorted(row['periods'])
        if preserved_periods(periods):
            continue
        key = (row['provider'], row['booking_ref'])
        stay = _stay(periods)
        try:
            nights = (date.fromisoformat(stay[1]) - date.fromisoformat(stay[0])).days if stay else None
        except ValueError:
            nights = None
        candidates = []
        service = any('항공' in label for label in row['labels'])
        for trip in trips:
            relation = _relation(stay, trip, service=service, handover=handover)
            if relation != 'none':
                candidates.append({**trip, 'relation': relation})
        candidates.sort(key=lambda c: (c['relation'] != 'covers', c['starts_on'], c['tab_id']))
        rule = rules.get(key)
        rule_view = None
        if rule:
            trip = trip_by_id.get(rule['trip_tab_id'])
            rule_view = {**rule, 'trip_name': trip['name'] if trip else rule['trip_code'],
                         'trip_valid': bool(trip and trip['valid']),
                         'trip_reason': (trip['reason'] if trip else '여행이 삭제되었거나 보관되었습니다')}
        portal = [{'id': tab, 'name': name, 'source': 'portal'} for tab, name in sorted(row['portal_trips'])]
        ledger = [{'id': tab, 'name': name, 'source': 'ledger'} for tab, name in sorted(row['ledger_trips'])]
        assigned = portal + ledger + ([{'id': rule['trip_tab_id'], 'name': rule_view['trip_name'], 'source': 'rule'}]
                                      if rule_view else [])
        revoked = states.get(key, {}).get('status') == 'revoked'
        # 취소되지 않은 예약은 이용기간에 맞는 검증된 여행으로 배정한다. 해제한 예약은 제외한다.
        period_trip = None
        codes = set(row['statuses'])
        if not assigned and not revoked and stay and len(periods) == 1 and 'cancelled' not in codes:
            period_trip = _automatic_trip(trips, stay, service=service, nets=nets)
            if period_trip:
                assigned = [period_trip]
                if not any(c['tab_id'] == period_trip['id'] for c in candidates):
                    candidates.append({**trip_by_id[period_trip['id']], 'relation': 'preparation'})
        entries.append({'period_trip': period_trip, 'revoked': revoked,
                        'reason': _unassigned_reason({'trips': assigned, 'status_codes': sorted(codes),
                                                      'stay': stay, 'candidates': candidates,
                                                      'conflict': len(periods) > 1}, revoked),
            'provider': row['provider'], 'booking_ref': row['booking_ref'],
            'identity_kind': row.get('identity_kind','supplier_booking'),
            'supplier_booking_ref': row.get('supplier_booking_ref',row['booking_ref']),
            'label': ' · '.join(sorted(row['labels'])),
            'starts_on': periods[0][0] if periods else '',
            'start_dates': [start for start, _ in periods if start],
            'periods': periods, 'stay': stay, 'nights': nights,
            'period': ' / '.join(f'{start or "미확인"} ~ {end or "미확인"}' for start, end in periods),
            'status': ' / '.join(STATUSES.get(s, s) for s in sorted(row['statuses'])),
            'status_codes': sorted(row['statuses']),
            'conflict': len(periods) > 1,
            'trips': assigned, 'rule': rule_view,
            'candidates': candidates,
            'card_matches': live.get(key, []),
            'card_candidates': reservation_candidates.get(key, []),
            'reservation_links': reservation_links.get(key, []),
            'payment_links': payment_links.get(key, []),
            'card_reconciliation_pending': card_error,
            'cancelled_matches': cancelled.get(key, 0),
        })
    return {'entries': entries, 'warnings': warnings, 'trips': trips,
            'months': sorted({day[:7] for r in entries for day in r['start_dates']
                              if re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)}),
            'providers': sorted({r['provider'] for r in entries})}


def _index_path(board):
    return Path(board.path).parent / INDEX_FILE


def _load_saved_index(board, key):
    """A saved index whose inputs are unchanged, or None. A damaged file is simply rebuilt."""
    try:
        saved = json.loads(_index_path(board).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or saved.get('key') != key:
        return None
    return saved.get('value')


def _saved_value_for_stale(board):
    """The last saved index whatever its key, so a restart can show the previous evidence at once."""
    try:
        saved = json.loads(_index_path(board).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or saved.get('version') != INDEX_VERSION:
        return None
    return saved.get('value')


def _save_index(board, key, value):
    """Write beside the board atomically; report failure so stale evidence stays marked stale."""
    path = _index_path(board)
    temp = path.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps({'version': INDEX_VERSION, 'key': key, 'value': value},
                                   ensure_ascii=False, default=str), encoding='utf-8')
        os.replace(temp, path)
        return True
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass
        return False


_REBUILD = {'running': False, 'active_key': None, 'failed_key': None, 'failed_at': 0.0}
_REBUILD_LOCK = threading.Lock()


def rebuilding() -> bool:
    with _REBUILD_LOCK:
        return _REBUILD['running']


def rebuild_failed() -> bool:
    """Whether the last background refresh failed, leaving saved evidence stale."""
    with _REBUILD_LOCK:
        return bool(_REBUILD['failed_key']) and not _REBUILD['running']


def refresh_state(board, sources):
    """Minimal state for the owner's page; never expose the bookings or their key."""
    key = _signature(board, sources)
    with _INDEX_LOCK:
        if _INDEX['key'] == (id(board), key):
            return 'ready'
    with _REBUILD_LOCK:
        if _REBUILD['running']:
            return 'running'
        if _REBUILD['failed_key'] == key:
            return 'failed'
    return 'pending'


def _start_rebuild(board, sources, key):
    with _REBUILD_LOCK:
        if _REBUILD['running']:
            return
        # A broken source must not start another expensive refresh on every page view.
        if _REBUILD['failed_key'] == key and time.monotonic() - _REBUILD['failed_at'] < 60:
            return
        _REBUILD['running'] = True
        _REBUILD['active_key'] = key
        _REBUILD['failed_key'] = None

    def rebuild_in_background():
        active_key = key
        try:
            # Computation never holds the publication/read lock.
            with _INDEX_BUILD_LOCK:
                with _INDEX_LOCK:
                    if _INDEX['key'] == (id(board), active_key):
                        return
                active_sources = sources
                for attempt in range(2):
                    value = _build_index(board, active_sources)
                    current_sources = configured_sources(board)
                    current_key = _signature(board, current_sources)
                    if current_key != active_key:
                        if attempt:
                            active_key = current_key
                            raise RuntimeError('OTA_REFRESH_INPUTS_CHANGED')
                        active_key, active_sources = current_key, current_sources
                        with _REBUILD_LOCK:
                            _REBUILD['active_key'] = active_key
                        continue
                    if not _save_index(board, active_key, value):
                        raise OSError('OTA_INDEX_SAVE_FAILED')
                    with _INDEX_LOCK:
                        _INDEX['value'] = value
                        _INDEX['key'] = (id(board), active_key)
                    return
        except Exception as exc:
            # Do not log booking contents, transaction details or source paths.
            logging.getLogger(__name__).error('OTA index refresh failed: %s', type(exc).__name__)
            with _REBUILD_LOCK:
                _REBUILD['failed_key'] = active_key
                _REBUILD['failed_at'] = time.monotonic()
        finally:
            with _REBUILD_LOCK:
                _REBUILD['running'] = False
                _REBUILD['active_key'] = None

    threading.Thread(target=rebuild_in_background, name='ota-index-rebuild', daemon=True).start()


def _index(board, sources, *, rebuild=False, allow_stale=False):
    """The booking index for these sources and this board state. Rebuilt only when an input changes.

    With allow_stale, a changed state returns the last index at once and rebuilds it in the background,
    so a page that only shows evidence does not wait for the rebuild."""
    key = _signature(board, sources)
    with _INDEX_LOCK:
        if _INDEX['key'] == (id(board), key):
            return _INDEX['value']
        stale = _INDEX['value'] if _INDEX['key'] and _INDEX['key'][0] == id(board) else None
    if allow_stale and not rebuild:
        if stale is None:
            stale = _saved_value_for_stale(board)
        _start_rebuild(board, sources, key)
        return stale if stale is not None else {
            'entries': [], 'warnings': [], 'trips': [], 'months': [], 'providers': []}
    with _INDEX_BUILD_LOCK:
        key = _signature(board, sources)
        with _INDEX_LOCK:
            if _INDEX['key'] == (id(board), key):
                return _INDEX['value']
        value = None if rebuild else _load_saved_index(board, key)
        built = value is None
        if value is None:
            value = _build_index(board, sources)
        if built and not _save_index(board, key, value):
            raise OSError('OTA_INDEX_SAVE_FAILED')
        with _INDEX_LOCK:
            _INDEX['value'] = value
            _INDEX['key'] = (id(board), key)
        return value


def prewarm(board):
    """Rebuild at startup, isolating source parsing from the HTTP interpreter."""
    try:
        board._catalog_source_process = True
        _index(board, configured_sources(board), rebuild=True)
    except Exception:
        # The first visit builds it again and shows its own warning, so nothing is hidden here.
        pass


def _linked_card_count(entry):
    if not entry.get('payment_links'):
        return len(entry['card_matches'])
    matches = list(entry['card_matches']) + list(entry['payment_links'])
    return len({m['transaction_id'] for m in matches if m.get('transaction_id')}) + sum(
        1 for m in entry['card_matches'] if not m.get('transaction_id'))


def _payment_links_html(row):
    esc = lambda value: html.escape(str(value or ''))
    amount_text = lambda value: f'{value:,}원' if type(value) in (int, float) else '원화 미확인'
    links = row.get('payment_links') or ()
    return ''.join('<br><small>연결된 카드 · ' + esc(link.get('day')) + ' · ' +
        esc(link.get('merchant')) + ' · ' + esc(amount_text(link.get('amount_krw'))) +
        (f" · M:N {link.get('booking_count') or link['event_count']}:{link['card_count']}" if (link.get('booking_count') or link.get('event_count', 0)) > 1
         or link.get('card_count', 0) > 1 else '') +
        (' · 그룹 금액 차이' if link.get('balance') == 'AMOUNT_DIFFERENCE' else '') +
        (' · 원문 결제일 미기록' if not link.get('payment_date_verified') else '') + '</small>'
        for link in links)


def _public_row(entry):
    return {'provider': entry['provider'], 'booking_ref': entry['booking_ref'], 'label': entry['label'],
            'booking_ref_display': _booking_ref_display(entry),
            'identity_kind': entry.get('identity_kind','supplier_booking'),
            'starts_on': entry['starts_on'], 'start_dates': entry['start_dates'], 'period': entry['period'],
            'status': entry['status'], 'conflict': entry['conflict'],
            'reason': entry.get('reason'),
            'trips': [{k: v for k, v in trip.items() if k in ('id', 'name', 'source', 'basis', 'confidence', 'assignment_state')} for trip in entry['trips']],
            'rule': None if not entry['rule'] else {'trip_tab_id': entry['rule']['trip_tab_id'],
                                                    'revision': entry['rule']['revision'],
                                                    'trip_valid': entry['rule']['trip_valid']},
            'card_count': _linked_card_count(entry),
            'payment_links': list(entry.get('payment_links') or ()),
            'card_candidates': list(entry.get('card_candidates') or ()),
            'reservation_links': list(entry.get('reservation_links') or ())}


def catalog(board, query, *, sources=None, allow_stale=False):
    value = lambda key: str((query.get(key) or [''])[0]).strip()
    warnings = []
    try:
        sources = configured_sources(board) if sources is None else sources
    except (OSError, ValueError, ota_sources.OtaSourcesError):
        sources = {}
        warnings.append('OTA 자료 설정을 읽지 못했습니다. 관리자 설정을 확인해 주세요.')
    index = _index(board, sources, allow_stale=allow_stale)
    state = refresh_state(board, sources) if allow_stale else 'ready'
    with _INDEX_LOCK:
        if state == 'ready' and allow_stale and _INDEX['value'] is not index:
            state = 'pending'
    entries = index['entries']
    all_count = len(entries)
    needs_assignment = lambda e: not e['trips'] and e['reason'] not in ('cancelled', 'revoked')
    unassigned_count = sum(needs_assignment(entry) for entry in entries)
    excluded_count = sum(not e['trips'] and e['reason'] in ('cancelled', 'revoked') for e in entries)
    month = value('month')
    if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', month):
        month = ''
    rows = [entry for entry in entries
        if (value('state') != 'unassigned' or needs_assignment(entry))
        and (value('state') != 'excluded' or (not entry['trips'] and entry['reason'] in ('cancelled', 'revoked')))
        and (not value('provider') or entry['provider'] == value('provider'))
        and (not month or any(day.startswith(month) for day in entry['start_dates']))
        and (not value('q') or value('q').casefold() in ' '.join((entry['booking_ref'], entry['provider'],
            PROVIDERS.get(entry['provider'], ''), entry['label'], entry['period'],
            *(t['name'] for t in entry['trips']))).casefold())]
    known = sorted((r for r in rows if r['starts_on']),
        key=lambda r: (r['starts_on'], r['provider'], r['booking_ref']), reverse=value('sort') == 'desc')
    rows = known + sorted((r for r in rows if not r['starts_on']), key=lambda r: (r['provider'], r['booking_ref']))
    total = len(rows)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    try:
        page = min(pages, max(1, int(value('page') or '1')))
    except ValueError:
        page = 1
    reasons = Counter(entry['reason'] for entry in entries if needs_assignment(entry))
    return {'rows': [_public_row(entry) for entry in rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]],
            'reasons': [{'code': code, 'label': UNASSIGNED_REASONS[code], 'count': count}
                        for code, count in reasons.most_common()],
            'all_count': all_count, 'unassigned_count': unassigned_count, 'excluded_count': excluded_count,
            'inferred_count': sum(bool(e.get('period_trip')) for e in entries), 'total': total, 'page': page,
            'pages': pages, 'months': index['months'], 'providers': index['providers'],
            'warnings': list(dict.fromkeys(warnings + index['warnings'])),
            'trip_problems': [trip for trip in index['trips'] if not trip['valid']],
            'trip_count': len(index['trips']), 'refresh_state': state}


def _entry(board, sources, provider, booking_ref):
    index = _index(board, sources)
    for entry in index['entries']:
        if entry['provider'] == provider and entry['booking_ref'] == booking_ref:
            return {**entry, 'correction_trips': index['trips']}
    return None


def _card_states(board, transaction_ids):
    """Current state of the card rows a booking points at: where they sit and whether a person decided them."""
    if not transaction_ids:
        return {}
    from app.db import decided_sql
    marks = ','.join('?' * len(transaction_ids))
    with board._lock:
        rows = board.conn.execute(
            f"SELECT t.transaction_id,b.batch_id,t.merchant,t.approval_date,t.posting_date,t.amount_krw,"
            f"t.classification_state,t.display_tab_id,t.item,{decided_sql('t')},"
            f"EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id) "
            f"FROM transactions t LEFT JOIN import_batch_rows b ON b.transaction_id=t.transaction_id "
            f"WHERE t.transaction_id IN ({marks})", list(transaction_ids)).fetchall()
    return {row[0]: {'batch_id': row[1] or '', 'merchant': row[2] or '', 'day': row[3] or row[4] or '',
                     'amount_krw': row[5], 'state': row[6] or '', 'tab': row[7] or '', 'item': row[8] or '',
                     'decided': bool(row[9]), 'already_booked': bool(row[10])} for row in rows}


def _state_label(card):
    if card is None:
        return '카드 자료에서 찾지 못함'
    if card['decided']:
        return '사용자가 지출 정리에서 정한 거래 · 예약 배정 적용 안 됨'
    if card.get('already_booked'):
        return '장부 기록됨'
    if card['state'] == 'classified':
        return '분류됨' + (f" · {card['tab']}" if card['tab'] and card['tab'] != 'unclassified' else '')
    if card['state'] == 'needs_review':
        return '확인 필요'
    return card['state'] or '미확인'


def _summary(entry, rule_active):
    """One plain sentence: what the owner can do with this booking right now."""
    if 'cancelled' in entry['status_codes'] or entry['status'] == '취소':
        return '취소된 예약이라 여행에 배정하지 않습니다.'
    if rule_active:
        trip = entry['rule']
        if trip['trip_valid']:
            return f"여행 「{trip['trip_name']}」에 배정되어 있습니다. 카드 결제 {len(entry['card_matches'])}건에 적용됩니다."
        return f"「{trip['trip_name']}」에 배정되어 있지만 그 여행의 일정 원본을 다시 확인해야 적용됩니다."
    period = [t for t in entry['trips'] if t.get('source') == 'period']
    if period:
        return (f"여행 「{period[0]['name']}」에 자동 추론 배정되었습니다. "
                f"{period[0].get('basis', '예약 이용기간 일치')} · 확신 {period[0].get('confidence', '보통')}. 아래에서 수정할 수 있습니다.")
    if entry.get('revoked'):
        return '사용자가 배정을 해제한 예약입니다. 자동으로 다시 배정하지 않습니다.'
    if entry.get('conflict'):
        return '이용기간 원본이 충돌하여 자동 배정을 보류했습니다. 근거를 확인해 여행을 수정할 수 있습니다.'
    if not entry['stay']:
        return '이용기간이 없어 여행 미배정입니다.'
    if any(c['valid'] for c in entry['candidates']):
        return '같은 조건의 여행이 둘 이상이고 수입-비용 차액도 같아 여행 미배정입니다.'
    if entry['candidates']:
        return '이용기간과 겹치는 여행의 일정 원본이 확인되지 않아 여행 미배정입니다.'
    return '이용기간과 겹치는 여행이 없어 여행 미배정입니다.'


def _booking_ref_display(entry):
    if entry.get('identity_kind')=='reservation_observation':
        return entry.get('supplier_booking_ref') or '원문 미제공'
    return entry.get('booking_ref') or '원문 미제공'


def render_html(data, query, *, csrf=''):
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

    sort = 'desc' if value('sort') == 'desc' else 'asc'
    date_controls = choices('sort', [('desc', '내림차순 · 최근 이용 먼저'), ('asc', '오름차순 · 이른 이용 먼저')], sort)
    date_controls += choices('month', [('', '전체 월')] + [(m, m + '월') for m in data['months']], value('month'))
    provider_controls = choices('provider', [('', '모든 OTA')] + [(p, PROVIDERS.get(p, p)) for p in data['providers']], value('provider'))
    state_controls = choices('state', [('', '전체 내역'), ('unassigned', '여행 미배정'), ('excluded', '취소·배정 해제')], value('state'))
    # 단일 상태에만 badge를 붙인다. 'A / B'처럼 합쳐진 문자열은 임의로
    # 확정하지 않고 문구 그대로 둔다. 수집됨(observed) 등 나머지 원값도
    # badge 없이 문구만 표시한다.
    STATUS_BADGE = {'예약 확정': ('check', 'ok'), '이용 완료': ('archive', 'ok'),
                    '취소': ('x-circle', 'bad'), '미확인': ('search', 'idle')}
    body = []
    for row in data['rows']:
        names = ' · '.join(esc(t['name']) for t in row['trips'])
        if names:
            rule = row.get('rule')
            suffix = f" · 규칙 r{rule['revision']}" if rule else ''
            if any(t.get('source') == 'period' for t in row['trips']):
                inferred = next(t for t in row['trips'] if t.get('source') == 'period')
                suffix += ' · 자동 추론 · 확신 ' + inferred.get('confidence', '보통')
            trip_cell = (f"<span class='ota-badge trip ok'>{ui_icons.icon('check', 14)}"
                         f"<span>{names}{esc(suffix)}</span></span>")
            if any(t.get('source') == 'period' for t in row['trips']):
                trip_cell += '<br><small>' + esc(inferred.get('basis')) + '</small>'
        else:
            trip_cell = (f"<span class='ota-badge trip idle'>{ui_icons.icon('map', 14)}"
                         "<span>여행 미배정</span></span>")
        if not names and row.get('reason') in ('cancelled', 'revoked'):
            trip_cell = "<span class='ota-badge trip idle'>배정 제외 · " + esc(UNASSIGNED_REASONS[row['reason']]) + '</span>'
        trip_cell += (f" <a href='{esc(detail_url(row['provider'], row['booking_ref']))}'>"
                      + ('여행 수정' if names else '판단하기') + '</a>')
        status = row['status'] or '미확인'
        badge = STATUS_BADGE.get(status)
        if badge is not None:
            icon, tone = badge
            status_cell = (f"<span class='ota-badge {tone}'>"
                           f"{ui_icons.icon(icon, 14)}{esc(status)}</span>")
        else:
            status_cell = esc(status)
        conflict = (f"<br><strong>{ui_icons.icon('alert-triangle', 16)}기간 확인 필요</strong>"
                    if row['conflict'] else '')
        body.append('<tr>' + ''.join(f"<td data-label='{label}'>{text}</td>" for label, text in (
            ('이용일', esc(row['period'] or '미확인') + conflict),
            ('OTA', esc(PROVIDERS.get(row['provider'], row['provider']))),
            ('예약번호', f"<a href='{esc(detail_url(row['provider'], row['booking_ref']))}'>{esc(row.get('booking_ref_display', _booking_ref_display(row)))}</a>"),
            ('예약 내용', esc(row['label'] or '미확인')), ('예약 상태', status_cell),
            ('카드 결제', esc(f"{row.get('card_count', 0)}건") + _payment_links_html(row) +
             (f"<br><small>예약 후보 {len(row['card_candidates'])}건 · 결제 미확정</small>"
              if row.get('card_candidates') else '') +
             ("<br><small>예약 관계: " + esc(' / '.join(
                 f"{'예약 추론 연결' if link.get('status') == 'INFERRED' else '사용자 예약 관계 확인' if link.get('status') == 'USER_CONFIRMED' else '근거 변경 · 재확인 필요' if link.get('status') == 'STALE' else '예약 관계 확인 필요'} · 결제 미검증 · {link.get('merchant') or '카드 자료에서 찾지 못함'} · {link.get('day') or '날짜 미확인'} · 원화 {link.get('amount_krw') if link.get('amount_krw') is not None else '미확인'} · {'금액 일치' if link.get('amount_status') == 'MATCH' else '금액 차이' if link.get('amount_status') == 'MISMATCH' else '금액 미확인'}"
                 for link in row.get('reservation_links') or ())) + "</small>"
              if row.get('reservation_links') else '')),
            ('여행 배정', trip_cell))) + '</tr>')
    hidden = ''.join(f"<input type='hidden' name='{k}' value='{esc(value(k))}'>" for k in ('state', 'provider', 'month', 'sort'))
    problems = data.get('trip_problems') or []
    reasons = data.get('reasons') or []
    reason_block = ''
    if reasons:
        items = ''.join(f"<tr><td>{esc(r['label'])}</td><td>{r['count']:,}건</td></tr>" for r in reasons)
        reason_block = (f"<section class='trip-check' aria-labelledby='reason-title'>"
                        f"<h2 id='reason-title'>여행 미배정 사유 · {data['unassigned_count']:,}건</h2>"
                        f"<table><tbody>{items}</tbody></table></section>")
    problem_block = ''
    if problems:
        items = ''.join(f"<li><strong>{esc(t['name'])}</strong> · {esc(t['reason'])}</li>" for t in problems[:30])
        problem_block = (f"<section class='trip-check' aria-labelledby='trip-check-title'>"
                         f"<h2 id='trip-check-title'>여행 일정 확인 필요 {len(problems):,}개 / 전체 {data.get('trip_count', 0):,}개</h2>"
                         "<p class='small'>일정 원본이 확인되지 않은 여행에는 예약을 배정할 수 없습니다. "
                         "원본을 다시 확인해 일정을 맞춘 뒤 배정해 주세요.</p>"
                         f"<ul>{items}</ul></section>")
    state = data.get('refresh_state', 'ready')
    loading = state != 'ready' and not data['all_count']
    refresh_note = '' if state == 'ready' else (
        "<p id='ota-catalog-refresh' role='status'>" +
        (('자료 갱신에 실패했습니다. 아직 저장된 자료가 없습니다.' if loading else
          '자료 갱신에 실패했습니다. 이전 자료를 표시합니다.') if state == 'failed' else
         'OTA 자료를 불러오는 중입니다.' if loading else
         'OTA 자료 갱신 중 · 이전 자료를 표시합니다. 갱신이 끝나면 다시 표시합니다.') + '</p>')
    refresh_script = '' if state in ('ready', 'failed') else """
<script>(()=>{let wait=1500;async function check(){try{const r=await fetch('/api/ota-refresh-state',{cache:'no-store'});if(!r.ok)throw Error();const j=await r.json();if(j.state==='ready'){location.reload();return}if(j.state==='failed'){document.getElementById('ota-catalog-refresh').textContent='자료 갱신에 실패했습니다. 이전 자료를 표시합니다.';return}}catch{}wait=Math.min(10000,wait*1.5);setTimeout(check,wait)}setTimeout(check,wait)})();</script>"""
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        '<title>OTA 내역</title><style>' + CATALOG_STYLE + OTA_STYLE +
        '</style></head><body><main class="card-catalog"><h1>OTA 내역</h1>'
        f"<nav class='catalog-actions' aria-label='OTA 내역 선택'><a class='catalog-btn{' primary' if not value('state') else ''}' href='{esc(url(state='', page=1))}'>{ui_icons.icon('list')}전체 예약</a>"
        f"<a class='catalog-btn{' primary' if value('state') == 'unassigned' else ''}' href='{esc(url(state='unassigned', page=1))}'>{ui_icons.icon('map')}여행 미배정</a>"
        f"<a class='catalog-btn' href='{esc(url(state='excluded', page=1))}'>취소·배정 해제 {data.get('excluded_count', 0):,}건</a>"
        f"<a class='catalog-btn' href='/import#ota-review'>{ui_icons.icon('credit-card')}카드 대사·검토</a></nav>"
        + refresh_note
        + ('' if loading else f"<p id='card-count'>{ui_icons.icon('list', 16)}전체 {data['all_count']:,}건 · 자동 추론 {data.get('inferred_count', 0):,}건 · 여행 미배정 {data['unassigned_count']:,}건 · 취소·해제 제외 {data.get('excluded_count', 0):,}건 · 검색 결과 {data['total']:,}건</p>")
        + ''.join(f"<p role='alert'>{ui_icons.icon('alert-triangle', 16)}{esc(w)}</p>" for w in data['warnings'])
        + reason_block + problem_block
        + f"<form id='card-filters' action='/ota' method='get'><input name='q' aria-label='OTA 내역 검색' placeholder='예약번호·예약 내용·여행 검색' value='{esc(value('q'))}'>"
        f"<button class='catalog-btn primary' type='submit'>{ui_icons.icon('search')}검색</button><a class='catalog-btn' href='/ota'>초기화</a>{hidden}</form>"
        '<table><thead><tr>' + heading('date', '이용일', date_controls) + heading('provider', 'OTA', provider_controls)
        + '<th>예약번호</th><th>예약 내용</th><th>예약 상태</th><th>카드 결제</th>' + heading('state', '여행 배정', state_controls)
        + '</tr></thead><tbody>' + (''.join(body) or ("<tr><td colspan='7'>OTA 자료 갱신에 실패했습니다.</td></tr>" if state == 'failed' and loading else "<tr><td colspan='7'>OTA 자료를 불러오는 중입니다.</td></tr>" if loading else f"<tr><td colspan=\"7\">{ui_icons.icon('search', 16)}조건에 맞는 OTA 예약이 없습니다.</td></tr>"
            if data['all_count'] else f"<tr><td colspan=\"7\">{ui_icons.icon('search', 16)}조회된 OTA 예약이 없습니다. 수집 자료 연결 상태를 확인해 주세요.</td></tr>"))
        + f"</tbody></table><nav class='catalog-pagination' aria-label='페이지 이동'><span>{data['page']} / {data['pages']} 페이지</span>"
        + (f"<a class='catalog-btn' href='{esc(url(page=data['page']-1))}'>이전</a>" if data['page'] > 1 else '')
        + (f"<a class='catalog-btn' href='{esc(url(page=data['page']+1))}'>다음</a>" if data['page'] < data['pages'] else '')
        + '</nav><script>' + CATALOG_SCRIPT + '</script>' + refresh_script + '</main></body></html>')


OTA_STYLE = (
    "@media(prefers-color-scheme:dark){.card-catalog{--cc-bg:#111820;--cc-surface:#1B2632;--cc-text:#E7EDF4;--cc-muted:#A7B4C2;--cc-border:#394858;--cc-soft:#24313E;--cc-accent:#8ED3AD;--cc-accent-bg:#244536;--cc-focus:#86B7FF;color-scheme:dark}}"
    ".card-catalog td:before{display:none}@media(width < 760px){.card-catalog td:before{display:block;content:attr(data-label);font-size:12px;color:#667085;margin-bottom:4px}}"
    ".card-catalog :focus-visible{outline:3px solid var(--cc-focus,#2266F5);outline-offset:2px}"
    ".card-catalog svg.ic{width:16px;height:16px;vertical-align:-3px;pointer-events:none}"
    ".card-catalog svg.ic:first-child{margin-right:6px}"
    "@media(prefers-reduced-motion:reduce){.card-catalog svg.ic{transition:none}}"
    ".ota-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:999px;"
    "font-size:12px;font-weight:600;white-space:nowrap;max-width:100%}"
    ".ota-badge svg.ic{width:14px;height:14px;margin:0;vertical-align:0;flex:0 0 auto}"
    ".ota-badge.trip{white-space:normal;overflow-wrap:anywhere}"
    ".ota-badge.ok{background:var(--cc-accent-bg,#ECF5EF);color:var(--cc-accent,#166444)}"
    ".ota-badge.idle{background:var(--cc-soft,#F2F4F7);color:var(--cc-muted,#667085)}"
    ".ota-badge.bad{background:#FDECEC;color:#912018}"
    ".trip-check{border:1px solid var(--cc-border);background:var(--cc-surface);color:var(--cc-text);border-radius:12px;padding:12px 16px;margin:12px 0}"
    ".trip-check table{color:var(--cc-text)}.trip-check .small{color:var(--cc-muted)}"
    "@media(prefers-color-scheme:dark){.ota-badge.bad{background:#542B30;color:#FFC3C7}}"
    ".trip-check h2{font-size:15px;margin:0 0 6px}.trip-check ul{margin:8px 0 0;padding-left:18px}"
    ".ota-detail section{border:1px solid var(--cc-border,#E4E7EC);border-radius:12px;background:var(--cc-surface,#fff);padding:14px 16px;margin:12px 0}"
    ".ota-detail h2{font-size:15px;margin:0 0 8px}"
    ".ota-detail table{width:100%;border-collapse:collapse}"
    ".ota-detail td,.ota-detail th{padding:6px 8px;border-bottom:1px solid var(--cc-border,#EEF0F3);text-align:left;vertical-align:top}"
    ".ota-detail .verdict{font-weight:650;font-size:15px;margin:0 0 10px}"
    ".ota-detail .muted{color:var(--cc-muted,#667085)}.ota-detail .warn{color:var(--shell-danger,#912018)}"
    "@media(prefers-color-scheme:dark){.ota-detail .warn{color:var(--shell-danger,#FFC3C7)}}"
    ".ota-detail label.option{display:flex;gap:10px;align-items:flex-start;margin:6px 0}"
    ".ota-detail input,.ota-detail select,.ota-detail textarea{max-width:100%;min-height:44px;border:1px solid var(--cc-border,#D0D5DD);border-radius:8px;background:var(--cc-surface,#fff);color:var(--cc-text,#182230);padding:8px 10px;font:inherit}"
    ".ota-detail :focus-visible{outline:3px solid var(--cc-focus,#2266F5);outline-offset:2px}"
    ".ota-detail textarea{width:100%;min-height:72px}"
    ".ota-detail .notice{border:1px solid #B7DCC7;background:var(--cc-accent-bg,#ECF5EF);border-radius:10px;padding:10px 14px}"
    ".ota-detail .actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}"
)


def detail_url(provider, booking_ref, notice='', error=''):
    params = {'provider': provider, 'ref': booking_ref}
    if notice:
        params['notice'] = notice
    if error:
        params['error'] = error
    return '/ota/booking?' + urlencode(params)


def render_detail(board, entry, *, csrf, notice='', error=''):
    esc = lambda v: html.escape(str(v or ''), quote=True)
    store = _review_store()
    try:
        rule_record = store.booking_trip_rule(entry['provider'], entry['booking_ref']) if store else None
        history = store.booking_trip_history(entry['provider'], entry['booking_ref']) if store else []
    finally:
        if store is not None:
            store.close()
    rule_active = bool(rule_record and rule_record['status'] == 'active')
    card_states = _card_states(board, [c['transaction_id'] for c in entry['card_matches']])
    rows = []
    for card in entry['card_matches']:
        state = card_states.get(card['transaction_id']) or {}
        amount = card['paid_amount_krw']
        amount_text = '{:,}원'.format(amount) if isinstance(amount, int) else '미확인'
        link = ''
        if state.get('batch_id'):
            target = '/import?' + urlencode({'batch': state['batch_id'], 'transaction': card['transaction_id']})
            link = f"<a href='{esc(target)}'>지출 정리에서 보기</a>"
        rows.append(
            f"<tr><td>{esc(state.get('day') or card['paid_on'] or '미확인')}</td>"
            f"<td>{esc(card['merchant'] or state.get('merchant') or '미확인')}</td>"
            f"<td>{esc(amount_text)}</td>"
            f"<td>{esc(_state_label(state or None))}"
            + ("<br><small>추론 연결 · 아고다 결제일 미확인</small>" if card.get('inferred_link') else '')
            + ("<br><small>사용자 승인 순서 배정 · 개별 결제 근거 미확인</small>"
               if card.get('allocation_basis') == 'user_approved_stable_order' else
               "<br><small>반복 거래 순서 배정 · 개별 결제 근거 미확인</small>"
               if card.get('allocation_basis') == 'auto_stable_order' else
               "<br><small>사용자 확정 순서 배정 · 개별 결제 근거 미확인</small>"
               if card.get('allocation_basis') == 'frozen_user_confirmed_order' else '') + "</td>"
            f"<td>{link}</td></tr>")
    payment_table = ('<table><thead><tr><th>카드 이용일</th><th>가맹점</th><th>결제 금액</th><th>현재 상태</th><th></th></tr></thead>'
                     f"<tbody>{''.join(rows)}</tbody></table>") if rows else (
        "<p class='muted'>카드 대사 결과를 확인 중입니다. 잠시 뒤 다시 조회해 주세요.</p>"
        if entry.get('card_reconciliation_pending') else
        "<p class='muted'>대사된 카드 결제가 없습니다. 카드 결제 근거가 없으면 여행 배정은 규칙으로만 남고, "
        "카드 결제가 들어오면 그때 적용됩니다.</p>")
    stay_text = (f"{entry['stay'][0]} ~ {entry['stay'][1]}" + (f" · {entry['nights']}박" if entry['nights'] is not None else '')
                 if entry['stay'] else entry.get('period') or '미확인')
    options = []
    correction_options = []
    selected = rule_record['trip_tab_id'] if rule_active else (entry.get('period_trip') or {}).get('id')
    options_by_id = {c['tab_id']: c for c in entry['candidates']}
    for trip in entry.get('correction_trips', []):
        options_by_id.setdefault(trip['tab_id'], {**trip, 'relation': 'manual'})
    for candidate in options_by_id.values():
        relation = {'covers': '이용기간을 모두 포함', 'preparation': '준비 숙박 · 다음 여행',
                    'manual': '기간 근거 밖 · 사용자 교정'}.get(candidate['relation'], '일부만 겹침')
        reason = '' if candidate['valid'] else f"<br><span class='warn'>사용 불가: {esc(candidate['reason'])}</span>"
        checked = ' checked' if selected == candidate['tab_id'] else ''
        disabled = '' if candidate['valid'] else ' disabled'
        target_options = correction_options if candidate['relation'] == 'manual' else options
        target_options.append(
            f"<label class='option'><input type='radio' name='trip_tab_id' value='{esc(candidate['tab_id'])}'{checked}{disabled}>"
            f"<span><strong>{esc(candidate['name'])}</strong> · {esc(candidate['starts_on'])} ~ {esc(candidate['ends_on'])}"
            f" · {relation}{reason}</span></label>")
    candidate_block = ''.join(options) or ("<p class='muted'>이 이용기간과 겹치는 여행이 없습니다. "
                                           "여행 일정이 등록되면 이 화면에서 배정할 수 있습니다.</p>")
    if correction_options:
        opened = ' open' if selected and selected not in {c['tab_id'] for c in entry['candidates']} else ''
        candidate_block += (f"<details{opened}><summary>다른 여행으로 수정</summary>"
                            + ''.join(correction_options) + '</details>')
    default_basis = rule_record['basis'] if rule_record else (
        f"예약 이용기간 {stay_text}과 여행 일정을 대조해 배정" if entry['stay'] else '')
    partial_needed = any(c['relation'] in ('overlaps', 'preparation', 'manual') for c in options_by_id.values())
    ledger_names = ', '.join(t['name'] for t in entry['trips'] if t.get('source') in ('ledger', 'portal'))
    notice_text = NOTICES.get(notice, '')
    message = ERROR_TEXT.get(error, error)
    history_rows = ''.join(
        f"<tr><td>{h['revision']}</td><td>{esc(h['trip_code'])}</td><td>{'배정' if h['status'] == 'active' else '해제'}</td>"
        f"<td>{esc(h['basis'])}</td><td>{esc(h['user'])}</td><td>{esc(h['changed_at'])}</td></tr>"
        for h in history)
    history_block = (f"<section><h2>배정 변경 이력</h2><table><thead><tr><th>r</th><th>여행</th><th>상태</th>"
                     f"<th>근거</th><th>누가</th><th>언제</th></tr></thead><tbody>{history_rows}</tbody></table></section>"
                     if history else '')
    rule_text = (f"현재 배정: <strong>{esc(rule_record['trip_code'])}</strong> ("
                 f"{esc(rule_record['changed_at'])})" if rule_active else
                 ('배정이 해제되어 있습니다.' if rule_record else ('기간으로 정해진 배정이 있습니다. 바꾸려면 아래에서 여행을 고르세요.' if entry.get('period_trip') else '배정된 여행 규칙이 없습니다.')))
    can_revoke = rule_active or bool(entry.get('period_trip'))
    revoke_form = (f"<form method='post' action='/ota/booking/revoke'>"
                   f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"
                   f"<input type='hidden' name='provider' value='{esc(entry['provider'])}'>"
                   f"<input type='hidden' name='booking_ref' value='{esc(entry['booking_ref'])}'>"
                   f"<input type='hidden' name='expected_revision' value='{rule_record['revision'] if rule_record else 0}'>"
                   "<button type='submit'>배정 해제</button></form>") if can_revoke else ''
    assign_form = (f"<form method='post' action='/ota/booking/trip'>"
                   f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"
                   f"<input type='hidden' name='provider' value='{esc(entry['provider'])}'>"
                   f"<input type='hidden' name='booking_ref' value='{esc(entry['booking_ref'])}'>"
                   f"<input type='hidden' name='expected_revision' value='{rule_record['revision'] if rule_record else 0}'>"
                   f"<section><h2>여행 고르기</h2>{candidate_block}"
                   + (f"<label class='option'><input type='checkbox' name='allow_partial' value='1'>"
                      f"<span>이용기간이 일부만 겹치거나 기간 근거 밖인 여행도 선택한 근거로 배정합니다.</span></label>" if partial_needed else '')
                   + f"<label>배정 근거<textarea name='basis' maxlength='600'>{esc(default_basis)}</textarea></label>"
                   + "<div class='actions'><button type='submit'>"
                   + ('배정 개정 저장' if rule_active else '배정 저장') + "</button></div></section></form>") if options_by_id else ''
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            '<title>OTA 예약 판단</title><style>' + CATALOG_STYLE + OTA_STYLE + '</style></head>'
            "<body><main class='card-catalog ota-detail'>"
            "<p><a href='/ota'>OTA 내역으로</a></p>"
            f"<h1>{esc(PROVIDERS.get(entry['provider'], entry['provider']))} · {esc(_booking_ref_display(entry))}</h1>"
            + (f"<p class='notice' role='status'>{esc(notice_text)}</p>" if notice_text else '')
            + (f"<p role='alert' class='warn'>{esc(message)}</p>" if message else '')
            + "<section><h2>판단</h2>"
            f"<p class='verdict'>{esc(_summary(entry, rule_active))}</p>"
            f"<p>예약: {esc(entry['label'] or '미확인')} · 상태: {esc(entry['status'] or '미확인')}</p>"
            f"<p>이용기간: {esc(stay_text)}</p>"
            + (f"<p class='warn'>이용기간 근거가 여러 개입니다: {esc(entry['period'])}</p>" if entry['conflict'] else '')
            + (f"<p class='muted'>장부에 이미 기록된 여행: {esc(ledger_names)}</p>" if ledger_names else '')
            + f"<p>{rule_text}</p></section>"
            + f"<section><h2>카드 결제</h2>{payment_table}</section>"
            + assign_form
            + (f"<section><h2>배정 해제</h2><p class='muted'>기간으로 정해진 배정도 해제하면 다시 자동으로 붙지 않습니다.</p>{revoke_form}</section>" if can_revoke else '')
            + history_block
            + "</main></body></html>")


def _ensure_owner(is_owner):
    if not is_owner:
        raise _Refused('NOT_FOUND')


def _check_csrf(token, csrf):
    if not csrf or token != csrf:
        raise _Refused('CSRF_REQUIRED')


def _form(raw):
    try:
        values = parse_qs((raw or b'').decode('utf-8'), keep_blank_values=True)
    except UnicodeDecodeError:
        raise _Refused('INVALID_INPUT')
    return {key: items[0] for key, items in values.items()}


def _reclassify(board, transaction_ids):
    """Re-run classification for the card rows a booking points at, batch by batch."""
    if not transaction_ids:
        return
    from .card_flow import CardFlow
    from app import StoreError
    flow = CardFlow(board)
    marks = ','.join('?' * len(transaction_ids))
    with board._lock:
        batches = defaultdict(list)
        for batch_id, transaction_id in board.conn.execute(
                f"SELECT batch_id,transaction_id FROM import_batch_rows WHERE transaction_id IN ({marks})",
                list(transaction_ids)).fetchall():
            batches[batch_id].append(transaction_id)
    for batch_id, ids in batches.items():
        try:
            flow._classify(batch_id, transaction_ids=ids)
        except StoreError as exc:
            raise _Refused('REVIEW_UNAVAILABLE') from exc


def _redirect(handler, location):
    handler.send_response(303)
    handler.send_header('Location', location)
    handler.send_header('Content-Length', '0')
    handler.end_headers()


def _write_rule(board, sources, form, *, revoke):
    from app.ota_review import BookingTripError, OtaReviewStore
    from . import ota_payment_review
    provider = str(form.get('provider', '')).lower()
    booking_ref = str(form.get('booking_ref', '')).strip()
    try:
        expected = int(form.get('expected_revision', '0'))
    except ValueError:
        raise _Refused('INVALID_INPUT')
    entry = _entry(board, sources, provider, booking_ref)
    if entry is None:
        raise _Refused('NOT_FOUND')
    path = ota_payment_review.review_db_path()
    if not ota_payment_review.enabled() or not path or not Path(path).is_absolute():
        raise _Refused('REVIEW_STORE_UNCONFIGURED')
    if revoke:
        writer = OtaReviewStore(path)
        try:
            result = writer.revoke_booking_trip(provider=provider, booking_ref=booking_ref,
                                                expected_revision=expected, user='owner')
        except BookingTripError as exc:
            raise _Refused(exc.code) from exc
        finally:
            writer.close()
        _reclassify(board, [c['transaction_id'] for c in entry['card_matches']])
        return result
    trip_id = str(form.get('trip_tab_id', '')).strip()
    basis = str(form.get('basis', '')).strip()
    if 'cancelled' in entry['status_codes'] or entry['status'] == '취소':
        raise _Refused('BOOKING_CANCELLED')
    if not entry['stay'] and form.get('allow_partial') != '1':
        raise _Refused('NO_PERIOD')
    candidate = next((c for c in entry['candidates'] if c['tab_id'] == trip_id), None)
    if candidate is None and form.get('allow_partial') == '1':
        candidate = next(({**t, 'relation': 'manual'} for t in entry.get('correction_trips', [])
                          if t['tab_id'] == trip_id), None)
    if candidate is None or candidate['relation'] == 'none':
        raise _Refused('TRIP_NOT_CANDIDATE')
    if not candidate['valid']:
        raise _Refused('TRIP_NOT_VERIFIED')
    if candidate['relation'] in ('overlaps', 'preparation') and form.get('allow_partial') != '1':
        raise _Refused('PARTIAL_NEEDS_CONFIRM')
    other = [t for t in entry['trips'] if t.get('source') not in ('rule', 'period') and t['id'] != trip_id]
    if other:
        raise _Refused('EXISTING_TRIP_DIFFERS')
    writer = OtaReviewStore(path)
    try:
        result = writer.save_booking_trip(provider=provider, booking_ref=booking_ref, trip_tab_id=trip_id,
                                          trip_code=candidate['name'], basis=basis,
                                          expected_revision=expected, user='owner')
    except BookingTripError as exc:
        raise _Refused(exc.code) from exc
    finally:
        writer.close()
    _reclassify(board, [c['transaction_id'] for c in entry['card_matches']])
    return result


def dispatch(handler, parsed, *, board, is_owner, query, csrf=''):
    """GET: list, detail, JSON. Returns False when the path is not an OTA path."""
    if parsed.path not in ('/ota', '/api/ota', '/ota/booking', '/api/ota-refresh-state'):
        return False
    if not is_owner:
        handler._send_json({'code': 'NOT_FOUND'}, 404)
    elif board is None:
        handler._send_json({'code': 'STORE_UNBOUND'}, 503)
    elif parsed.path == '/api/ota-refresh-state':
        try:
            sources = configured_sources(board)
            _index(board, sources, allow_stale=True)
            handler._send_json({'state': refresh_state(board, sources)})
        except (OSError, ValueError, sqlite3.Error, ota_sources.OtaSourcesError):
            handler._send_json({'state': 'failed'}, 503)
    elif parsed.path == '/ota/booking':
        try:
            sources = configured_sources(board)
        except (OSError, ValueError, ota_sources.OtaSourcesError):
            handler._send_json({'code': 'OTA_SOURCES_UNAVAILABLE', 'message': 'OTA 자료 설정을 확인해 주세요'}, 503)
            return True
        provider = str((query.get('provider') or [''])[0]).lower()
        ref = str((query.get('ref') or [''])[0]).strip()
        entry = _entry(board, sources, provider, ref)
        if entry is None:
            handler._send_json({'code': 'NOT_FOUND', 'message': ERROR_TEXT['NOT_FOUND']}, 404)
        else:
            handler._send(render_detail(board, entry, csrf=csrf,
                                        notice=str((query.get('notice') or [''])[0]),
                                        error=str((query.get('error') or [''])[0])))
    else:
        data = catalog(board, query, allow_stale=True)
        if parsed.path == '/api/ota':
            handler._send_json(data)
        else:
            handler._send(render_html(data, query, csrf=csrf))
    return True


def dispatch_post(handler, parsed, *, raw, csrf, board, is_owner):
    """POST: save or clear one booking's trip assignment. Owner and CSRF checks come first."""
    if parsed.path not in ('/ota/booking/trip', '/ota/booking/revoke'):
        return False
    if not is_owner:
        handler._send_json({'code': 'NOT_FOUND'}, 404)
        return True
    provider, ref = '', ''
    try:
        if board is None:
            raise _Refused('STORE_UNBOUND')
        form = _form(raw)
        provider = str(form.get('provider', '')).lower()
        ref = str(form.get('booking_ref', '')).strip()
        _check_csrf(form.get('csrf', ''), csrf)
        revoke = parsed.path.endswith('/revoke')
        _write_rule(board, configured_sources(board), form, revoke=revoke)
        _redirect(handler, detail_url(provider, ref, notice='revoked' if revoke else 'saved'))
    except _Refused as exc:
        if provider and ref and exc.code != 'NOT_FOUND':
            _redirect(handler, detail_url(provider, ref, error=exc.code))
        else:
            handler._send_json({'code': exc.code, 'message': ERROR_TEXT.get(exc.code, '')}, 409)
    return True
