"""수집이 멈췄는지 한눈에 보이도록 기존 기록만 읽는 상태 판.

새 테이블이나 경로를 만들지 않는다. 카드·메일·OTA·Google·P2 가 이미 남긴
기록을 읽기 전용으로 모아, 마지막 수집이 기준보다 오래됐으면 경고한다.
기록이 없으면 지어내지 않고 '기록 없음'으로 둔다. 인증 실패 기록이 있는
곳(Google)에서만 '로그인 필요'를 띄운다.
"""
import datetime as dt
import json
import os
import sqlite3
import time
from contextlib import closing
from html import escape as esc
from pathlib import Path

from app.reserve_trips import KST

# 원천별 '며칠 전' 경고 기준(일). 판정 규칙이 아니라 화면 표시 기준이다.
THRESHOLDS_DAYS = {
    'card': 7,
    'mail': 1,
    'ota': 30,
    'google': 1,
}

CARD_ISSUERS = (('국민', '국민카드'), ('하나', '하나카드'), ('기업', '기업카드'))
OTA_PROVIDERS = (('agoda', 'Agoda'), ('trip', 'Trip.com'), ('booking', 'Booking.com'),
                 ('foresttrip', '숲나들e'), ('sooperang', '산림치유원'))
NO_RECORD = '기록 없음'

# 홈 요청마다 수집 쿼리가 다시 돌지 않도록 하는 짧은 인프로세스 캐시(새 의존성 없음).
_CACHE_TTL_SECONDS = 60.0
_CACHE = {}


def _cache_clear():
    _CACHE.clear()


def _parse_kst(value, *, naive_tz=None):
    """여러 원천의 시각 문자열을 한국 시간으로 모은다. 읽을 수 없으면 None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_tz or KST)
    return parsed.astimezone(KST)


def _card_last(board):
    """발급사별 마지막 카드 파일 접수 시각. 거래 정본과 같은 DB에서 읽는다."""
    result = {}
    try:
        rows = board.conn.execute(
            "SELECT t.issuer, MAX(b.received_at) FROM import_batches b "
            "JOIN import_batch_rows r ON r.batch_id=b.batch_id "
            "JOIN transactions t ON t.transaction_id=r.transaction_id "
            "WHERE t.issuer IN ('국민','하나','기업') GROUP BY t.issuer").fetchall()
        for issuer, received in rows:
            result[issuer] = _parse_kst(received)
    except (sqlite3.Error, AttributeError, TypeError, ValueError):
        pass
    return result


def _mail_last(data_root):
    """Gmail 수집기가 남긴 collection.json 의 마지막 실행 시각(현지 한국 시간)."""
    mail_dir = os.environ.get('WEBLEDGER_OTA_MAIL_DIR') or str(data_root / 'ota-mail')
    try:
        state = json.loads((Path(mail_dir) / 'collection.json').read_text(encoding='utf-8'))
        return _parse_kst(state.get('last_run'), naive_tz=KST)
    except (OSError, ValueError, AttributeError):
        return None


def _ota_from_conn(conn, result):
    # Agoda·Trip.com·Booking 은 공급자별 직접 수집 원천의 마지막 접수 시각.
    for key, provider in (('agoda', 'agoda'), ('trip', 'trip'), ('booking', 'booking')):
        row = conn.execute(
            "SELECT MAX(r.observed_at) FROM ota_sources s "
            "JOIN ota_source_revisions r ON r.source_id=s.source_id "
            "WHERE s.kind='direct_observation' AND s.locator LIKE ?",
            ('direct/' + provider + '/%',)).fetchone()
        value = _parse_kst(row[0] if row else None)
        if value and (result[key] is None or value > result[key]):
            result[key] = value
    # 숲나들e·산림치유원은 같은 forest 공급자라 예약번호 앞자로 나눠 읽는다.
    # 예약에서 출발하는 조회만 근거 표를 빠르게 훑는다(역방향 조회는 느리다).
    # 근거가 최신 판이 아닌 옛 판에 있어도 놓치지 않도록 판의 출처로 잇는다.
    for key, prefix in (('foresttrip', 'foresttrip:%'), ('sooperang', 'sooperang:%')):
        row = conn.execute(
            "SELECT MAX(r.observed_at) FROM ota_bookings b "
            "JOIN ota_booking_evidence e ON e.booking_id=b.booking_id "
            "JOIN ota_source_revisions r ON r.revision_id=e.revision_id "
            "JOIN ota_sources s ON s.source_id=r.source_id "
            "WHERE b.provider='forest' AND s.kind='direct_observation' "
            "AND b.booking_number LIKE ?", (prefix,)).fetchone()
        value = _parse_kst(row[0] if row else None)
        if value and (result[key] is None or value > result[key]):
            result[key] = value


def _ota_last(data_root):
    """등록된 OTA 근거 DB 에서 공급자별 마지막 수집 시각. 없으면 그대로 비운다."""
    from app import ota_sources
    from app.ota_portal import evidence_path
    from app.ota_store import connect_read
    result = {key: None for key, _ in OTA_PROVIDERS}
    mail_default = os.environ.get('WEBLEDGER_OTA_MAIL_DIR') or (data_root / 'ota-mail')
    try:
        sources = ota_sources.resolve_sources(
            data_root, mail_default=mail_default, portal_default=evidence_path(data_root))
    except (ota_sources.OtaSourcesError, ValueError, OSError):
        return result
    for database in sources.get('portal_databases') or []:
        database = Path(database)
        if not database.is_file():
            continue
        try:
            with closing(connect_read(database)) as conn:
                _ota_from_conn(conn, result)
        except (sqlite3.Error, OSError, ValueError):
            continue
    return result


def _google_status():
    """Google 수입 동기화 스냅샷의 마지막 성공 시각과 인증 실패 기록 유무."""
    raw = os.environ.get('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', '').strip()
    if not raw:
        return None, False
    from app import google_authority
    try:
        snapshot = google_authority.load_snapshot(Path(raw))
    except (google_authority.SnapshotError, OSError, ValueError):
        return None, False
    last, login = None, False
    for record in (snapshot.get('sources') or {}).values():
        if not isinstance(record, dict):
            continue
        if record.get('error_code') == 'GOOGLE_AUTH_UNAVAILABLE':
            login = True
        ok = _parse_kst(record.get('last_ok_at'))
        if ok and (last is None or ok < last):
            last = ok
    return last, login


def _p2_status(config_path):
    """설정된 P2 보관함에서 가장 최근 실행 요약. 설정이 없으면 실행 기록 없음."""
    try:
        options = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    archive = options.get('p2_batch_archive') if isinstance(options, dict) else None
    if not isinstance(archive, str) or not archive.strip():
        return None
    best = None
    try:
        candidates = list(Path(archive).glob('*/summary.json'))
    except OSError:
        return None
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
            summary = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(summary, dict) or 'merchants' not in summary or 'successful_calls' not in summary:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, summary)
    if best is None:
        return None
    mtime, summary = best
    return {'last_at': dt.datetime.fromtimestamp(mtime, KST),
            'merchants': int(summary.get('merchants') or 0),
            'success': int(summary.get('successful_calls') or 0),
            'failed': int(summary.get('failed_attempts') or 0)}


def _normal_undecided(board):
    """판정 없는 정상 거래 수(M2 졸업 지표). 기준선 도구와 같은 정의를 쓴다."""
    try:
        conn = board.conn
        hold_filter = (
            "AND NOT EXISTS (SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id) "
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_review_holds'").fetchone() else '')
        exclusion_filter = (
            "AND NOT EXISTS (SELECT 1 FROM transaction_company_exclusions x "
            "WHERE x.transaction_id=t.transaction_id AND x.excluded=1) "
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_company_exclusions'").fetchone() else '')
        row = conn.execute(
            "SELECT COUNT(*) FROM transactions t WHERE t.transaction_direction='purchase' "
            "AND typeof(t.amount_krw)='integer' AND t.amount_krw>0 "
            "AND COALESCE(t.duplicate_of,'')='' AND COALESCE(t.conflict_reason,'')='' "
            "AND COALESCE(t.parse_error,'')='' " + hold_filter + exclusion_filter +
            "AND NOT (t.classification_state='classified' AND COALESCE(t.item,'')!='' "
            "AND (COALESCE(NULLIF(t.display_tab_id,''),NULLIF(t.trip_id,''),'') NOT IN ('','unclassified') "
            "OR t.item='분기 기타비용' OR t.classification_source='guide_airfare_evidence'))").fetchone()
        return int(row[0]) if row else None
    except (sqlite3.Error, AttributeError, TypeError, ValueError):
        return None


def gather(board, *, now=None):
    """원천별 마지막 수집 기록을 모은다. 기록이 없으면 None 으로 남긴다."""
    path = getattr(board, 'path', None)
    key = str(path) if (now is None and path is not None) else None
    if key is not None:
        hit = _CACHE.get(key)
        if hit is not None and time.monotonic() < hit[0]:
            return hit[1]
    now = now or dt.datetime.now(KST)
    data_root = Path(path).parent if path is not None else None
    cards = _card_last(board)
    mail = _mail_last(data_root) if data_root is not None else None
    ota = _ota_last(data_root) if data_root is not None else {key: None for key, _ in OTA_PROVIDERS}
    google_last, google_login = _google_status()
    try:
        from .google_ledger_page import last_trip_import_result
        trip_import = last_trip_import_result()
    except Exception:
        trip_import = None
    p2 = (_p2_status(Path(path).parent.parent / 'config' / 'card-flow.json')
          if path is not None else None)
    sources = [{'label': label, 'group': 'card', 'last_at': cards.get(issuer),
                'threshold': THRESHOLDS_DAYS['card'], 'login_required': False}
               for issuer, label in CARD_ISSUERS]
    sources.append({'label': 'Gmail 메일', 'group': 'mail', 'last_at': mail,
                    'threshold': THRESHOLDS_DAYS['mail'], 'login_required': False})
    sources.extend({'label': label, 'group': 'ota', 'last_at': ota.get(key),
                    'threshold': THRESHOLDS_DAYS['ota'], 'login_required': False}
                   for key, label in OTA_PROVIDERS)
    sources.append({'label': 'Google 수입', 'group': 'google', 'last_at': google_last,
                    'threshold': THRESHOLDS_DAYS['google'], 'login_required': google_login})
    data = {'now': now, 'sources': sources, 'p2': p2, 'trip_import': trip_import,
            'normal_undecided': _normal_undecided(board)}
    if key is not None:
        _CACHE[key] = (time.monotonic() + _CACHE_TTL_SECONDS, data)
    return data


def evaluate(record, now):
    """한 원천의 경과 일수와 상태 문구. 로그인 실패 기록이 가장 앞선다."""
    last = record.get('last_at')
    days = (now.date() - last.date()).days if last is not None else None
    if days is not None and days < 0:
        days = 0
    if record.get('login_required'):
        return {'days_ago': days, 'status': '로그인 필요', 'css': 'login'}
    if last is None:
        return {'days_ago': None, 'status': NO_RECORD, 'css': 'none'}
    threshold = record.get('threshold')
    if threshold is not None and days > threshold:
        return {'days_ago': days, 'status': '경고', 'css': 'warn'}
    return {'days_ago': days, 'status': '정상', 'css': 'ok'}


def _ago_text(days):
    if days is None:
        return ''
    return '오늘' if days == 0 else f'{days}일 전'


def render_html(data):
    """모아 둔 기록을 작은 표로 그린다. 내부 용어 대신 쉬운 말을 쓴다."""
    now = data['now']
    rows = []
    for record in data['sources']:
        state = evaluate(record, now)
        last = record.get('last_at')
        if last is None:
            last_text = NO_RECORD
        else:
            last_text = esc(last.strftime('%Y-%m-%d')) + ' · ' + _ago_text(state['days_ago'])
        threshold = record.get('threshold')
        threshold_text = f'{threshold}일' if threshold is not None else '—'
        title = f' title="기준 {threshold}일 초과"' if state['css'] == 'warn' else ''
        rows.append(
            f"<tr><td>{esc(record['label'])}</td><td>{last_text}</td>"
            f"<td>{threshold_text}</td><td class='{state['css']}'{title}>{state['status']}</td></tr>")
    p2 = data.get('p2')
    if p2:
        p2_text = (f"AI 판정 마지막 실행 {esc(p2['last_at'].strftime('%Y-%m-%d'))} · "
                   f"대상 {p2['merchants']}곳 · 성공 {p2['success']} · 실패 {p2['failed']}")
    else:
        p2_text = 'AI 판정 실행 기록 없음'
    normal = data.get('normal_undecided')
    normal_text = f'판정 없는 정상 거래 {normal}건' if normal is not None else '판정 없는 정상 거래 —'
    trip_import = data.get('trip_import') or {}
    schedule_text = ('Google 여행 일정 근거 파일을 읽지 못했습니다.'
                     if trip_import.get('schedule_unavailable') else '')
    suffix = (' · ' + schedule_text) if schedule_text else ''
    return (
        "<style>"
        ".home-collection{margin:0}"
        ".home-collection h3{font-size:var(--t-h3);margin:0 0 8px}"
        ".home-collection table{width:100%;border-collapse:collapse;font-size:var(--t-meta)}"
        ".home-collection th,.home-collection td{text-align:left;padding:4px 10px 4px 0;vertical-align:top}"
        ".home-collection th{color:var(--mut);font-weight:600}"
        ".home-collection .ok{color:var(--grn)}"
        ".home-collection .warn{color:var(--warn);font-weight:700}"
        ".home-collection .login{color:var(--neg);font-weight:700}"
        ".home-collection .none{color:var(--mut)}"
        ".home-collection-note{font-size:var(--t-meta);color:var(--mut);margin:8px 0 0}"
        "</style>"
        "<div class='home-collection' aria-label='수집 상태'>"
        "<h3>수집 상태</h3>"
        "<table><thead><tr><th>원천</th><th>마지막 수집</th><th>기준</th><th>상태</th></tr></thead>"
        "<tbody>" + ''.join(rows) + "</tbody></table>"
        f"<p class='home-collection-note'>{p2_text} · {normal_text}{esc(suffix)}</p>"
        "</div>")


def render(board):
    return render_html(gather(board))
