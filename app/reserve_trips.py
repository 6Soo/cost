"""reserve의 댓글 기준으로 여행을 등록한다. 비용 금액이나 전표는 만들지 않는다."""
import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

from ledger.domain.direct_trip_schedule_authority import SCHEMA_VERSION, END_SEMANTICS, validate_document

SOURCE_URL = 'https://reserve.foresttour.kr/api/public/ledger-trips'
SCHEMA = 'reserve-ledger-trips-v1'
KST = dt.timezone(dt.timedelta(hours=9))
FIELDS = {'source_key','fldid','post_id','title','trip_code','region','country','starts_on','ends_on',
          'event_year','end_semantics','authority_kind','authority_status','comment_count',
          'comment_threshold','departure_status','source_url','record_sha256'}
SQL = '''CREATE TABLE IF NOT EXISTS reserve_trip_registrations (
source_key TEXT PRIMARY KEY, trip_id TEXT NOT NULL UNIQUE, trip_code TEXT NOT NULL,
starts_on TEXT NOT NULL, ends_on TEXT NOT NULL, source_sha256 TEXT NOT NULL,
source_path TEXT NOT NULL, source_url TEXT NOT NULL, comment_count INTEGER,
departure_status TEXT NOT NULL, registered_at TEXT NOT NULL)'''
SCHEDULE_SQL = '''CREATE TABLE IF NOT EXISTS reserve_trip_sync_state (
id INTEGER PRIMARY KEY CHECK(id=1), next_run_at TEXT NOT NULL, status_json TEXT NOT NULL)'''


def today():
    return dt.datetime.now(KST).date().isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def fetch_records(url=SOURCE_URL):
    records, seen, offset, observed_day, total = [], set(), 0, None, None
    deadline = time.monotonic() + 180
    for _ in range(170):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('RESERVE_SOURCE_TIMEOUT')
        request = urllib.request.Request(url + '?offset=' + str(offset), headers={'User-Agent':'ForesttourLedger/1'})
        with urllib.request.urlopen(request, timeout=min(35,remaining)) as response:
            if response.geturl().split('?')[0] != url:
                raise ValueError('RESERVE_SOURCE_REDIRECTED')
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('RESERVE_SOURCE_TOO_LARGE')
        page = json.loads(data)
        if page.get('schema_version') != SCHEMA or page.get('comment_threshold') != 5:
            raise ValueError('RESERVE_SOURCE_SCHEMA_INVALID')
        if observed_day is not None and observed_day != page.get('today'):
            raise ValueError('RESERVE_SOURCE_DAY_CHANGED')
        observed_day = page.get('today')
        if total is not None and total != page.get('total'):
            raise ValueError('RESERVE_SOURCE_CATALOG_CHANGED')
        total = page.get('total')
        for record in page['records']:
            validate_record(record)
            if record['source_key'] in seen:
                raise ValueError('RESERVE_SOURCE_KEY_DUPLICATED')
            seen.add(record['source_key'])
            records.append(record)
        next_offset = page.get('next_offset')
        if next_offset is None:
            if len(records) != total:
                raise ValueError('RESERVE_SOURCE_INCOMPLETE')
            return records
        if type(next_offset) is not int or next_offset <= offset:
            raise ValueError('RESERVE_SOURCE_PAGINATION_INVALID')
        offset = next_offset
    raise ValueError('RESERVE_SOURCE_PAGE_LIMIT')


def validate_record(record):
    if set(record) != FIELDS:
        raise ValueError('RESERVE_SOURCE_FIELDS_INVALID')
    body = {k:v for k,v in record.items() if k != 'record_sha256'}
    if hashlib.sha256(encoded(body)).hexdigest() != record['record_sha256']:
        raise ValueError('RESERVE_SOURCE_HASH_INVALID')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', record['fldid']):
        raise ValueError('RESERVE_SOURCE_ID_INVALID')
    if (record['comment_count'] is not None and (type(record['comment_count']) is not int or record['comment_count'] < 0)
            or record['departure_status'] not in ('scheduled','schedule_unconfirmed','departed','comments_unavailable','below_threshold')):
        raise ValueError('RESERVE_STATUS_OR_COMMENTS_INVALID')
    start, end = record['starts_on'], record['ends_on']
    if record['departure_status'] != 'scheduled':
        return
    if (type(record['comment_count']) is not int or record['comment_count'] < 5
            or record['comment_threshold'] != 5 or record['authority_status'] != 'authoritative'
            or record['authority_kind'] not in ('explicit_trip_registry','user_confirmed_schedule')
            or record['end_semantics'] != END_SEMANTICS):
        raise ValueError('RESERVE_ELIGIBILITY_INVALID')
    try:
        first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except (ValueError, TypeError):
        raise ValueError('RESERVE_PERIOD_INVALID') from None
    if (last < first or record['event_year'] != first.year or not record['trip_code'] or not record['region']
            or record['source_key'] != f"reserve:{record['fldid']}:{first.year}"
            or not re.fullmatch(r'[1-9][0-9]*', record['post_id'] or '')
            or record['source_url'] != f"https://cafe.daum.net/sixsungwon/{record['fldid']}/{record['post_id']}"):
        raise ValueError('RESERVE_PERIOD_OR_SOURCE_INVALID')


def registrations(board):
    with board._lock:
        exists = board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='reserve_trip_registrations'").fetchone()
        if not exists:
            return {}
        names = [r[1] for r in board.conn.execute('PRAGMA table_info(reserve_trip_registrations)')]
        return {r[1]:dict(zip(names,r)) for r in board.conn.execute('SELECT * FROM reserve_trip_registrations')}


def sync_records(board, records, authority_path, evidence_root, *, day=None):
    day = day or today()
    for record in records:
        validate_record(record)
    if len({r['source_key'] for r in records}) != len(records):
        raise ValueError('RESERVE_SOURCE_KEY_DUPLICATED')
    authority_path, evidence_root = Path(authority_path), Path(evidence_root)
    result = Counter(created=0, linked=0, unchanged=0, held=0)
    with board._lock:
        board.conn.execute(SQL)
        board.conn.commit()
        document = json.loads(authority_path.read_text(encoding='utf-8'))
        validate_document(document)
        by_id = {r['source_key']:r for r in registrations(board).values()}
        for record in records:
            key = record['source_key']
            prior = by_id.get(key)
            if prior:
                trip = board.get_trip(prior['trip_id'])
                # 원천 일정 변경과 사람이 고친 여행은 자동으로 덮지 않는다.
                conflict = (not trip or trip['deleted'] or trip['archived']
                    or trip['display_key'] != prior['trip_code'] or trip['source_sha256'] != prior['source_sha256']
                    or any(trip[k] != prior[k] for k in ('starts_on','ends_on'))
                    or any(record[k] != prior[k] for k in ('starts_on','ends_on')))
                status = 'schedule_conflict' if conflict else record['departure_status']
                board.conn.execute('UPDATE reserve_trip_registrations SET comment_count=?,departure_status=? WHERE source_key=?',
                                   (record['comment_count'],status,key))
                board.conn.commit()
                result['held' if conflict else 'unchanged'] += 1
                continue
            if record['departure_status'] != 'scheduled' or record['starts_on'] < day:
                result['held'] += 1
                continue
            code = record['trip_code']
            destination = record['region']
            # 날짜가 반복된 긴 제목 대신 지역을 표시하고, 전체 제목은 원천에 보존한다.
            if destination == record['title'][:80]:
                short = next((r for r in ('하쿠산','서호주','경주','닛코','한옥스테이','한티','후지산')
                              if r in destination), None)
                if short and code == record['starts_on'][5:7]+record['starts_on'][8:10]+'_'+destination:
                    destination = short
                    code = record['starts_on'][5:7]+record['starts_on'][8:10]+'_'+short
            existing = [t for t in board.list_trips(include_archived=True) if t['display_key'] == code]
            if any(t['event_year'] != record['event_year'] for t in existing):
                code = str(record['event_year']) + '_' + code
                existing = [t for t in board.list_trips(include_archived=True) if t['display_key'] == code]
            same_date = board.find_trip_by_schedule(record['starts_on'],destination)
            if same_date and same_date['display_key'] != code:
                result['held'] += 1
                continue
            source_path = evidence_root / ('reserve-' + hashlib.sha256(key.encode()).hexdigest()[:24] + '.json')
            pending = source_path.is_file() and not prior
            if pending:
                pending_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
                if existing and existing[0]['source_sha256'] == pending_digest:
                    # 중단 직전 생성한 여행은 같은 요청 결과로 복구한다.
                    existing = []
            if existing:
                if len(existing) != 1 or any(existing[0][k] != record[k] for k in ('starts_on','ends_on')) or existing[0]['deleted'] or existing[0]['archived']:
                    result['held'] += 1
                    continue
                trip_id = existing[0]['tab_id']
                # 기존 원천과 담당자·사용자 수정을 유지하고 댓글 근거만 연결한다.
                source_path, digest = '', existing[0]['source_sha256']
                result['linked'] += 1
            else:
                snapshot = {'schema_version':SCHEMA,'registered_trip_code':code,'record':record}
                if source_path.exists():
                    snapshot = json.loads(source_path.read_text(encoding='utf-8'))
                    validate_record(snapshot['record'])
                    if (snapshot['registered_trip_code'] != code or any(snapshot['record'][k] != record[k]
                            for k in ('source_key','starts_on','ends_on'))):
                        result['held'] += 1
                        continue
                else:
                    atomic_write(source_path, encoded(snapshot))
                digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
                authority = dict(trip_code=code,event_year=record['event_year'],starts_on=record['starts_on'],
                    ends_on=record['ends_on'],region=destination,authority_kind=record['authority_kind'],
                    authority_status='authoritative',source_locator=str(source_path.resolve())+'#'+key,
                    source_sha256=digest,end_semantics=END_SEMANTICS)
                old = [r for r in document['records'] if r['trip_code'] == code]
                if old and old != [authority]:
                    raise ValueError('RESERVE_EXISTING_AUTHORITY_CONFLICT')
                if not old:
                    document['records'].append(authority)
                    validate_document(document)
                    atomic_write(authority_path, encoded(document))
                outcome = board.create_trip(starts_on=record['starts_on'],ends_on=record['ends_on'],
                    destination=destination,display_key=code,source_sha256=digest,
                    client_request_id='reserve-trip-' + hashlib.sha256(key.encode()).hexdigest(),actor='owner')
                trip_id = outcome['tab_id']
                result['created'] += int(outcome['created'])
            board.conn.execute('INSERT INTO reserve_trip_registrations VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (key,trip_id,code,record['starts_on'],record['ends_on'],digest,str(source_path),
                 record['source_url'],record['comment_count'],'scheduled',dt.datetime.now(dt.timezone.utc).isoformat()))
            board.conn.commit()
        board.reserve_trip_sync_status = dict(result,observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                              records=len(records),status='ok')
    return board.reserve_trip_sync_status


def next_midnight(now=None):
    moment = (now or dt.datetime.now(KST)).astimezone(KST)
    return (moment + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def sync_status(board):
    with board._lock:
        exists = board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='reserve_trip_sync_state'").fetchone()
        row = board.conn.execute('SELECT next_run_at,status_json FROM reserve_trip_sync_state WHERE id=1').fetchone() if exists else None
        return dict(json.loads(row[1]), next_run_at=row[0]) if row else getattr(board, 'reserve_trip_sync_status', {})


def initialize_sync_schedule(board, now=None):
    """첫 적용은 다음 0시부터 시작하며, 재시작할 때 기존 일정을 보존한다."""
    with board._lock:
        board.conn.execute(SCHEDULE_SQL)
        board.conn.execute('INSERT OR IGNORE INTO reserve_trip_sync_state VALUES (1,?,?)',
                           (next_midnight(now).isoformat(), json.dumps({'status':'waiting'})))
        state = sync_status(board)
        if state.get('status') == 'running':
            state.update(status='failed', error='RESERVE_SYNC_INTERRUPTED')
            board.conn.execute('UPDATE reserve_trip_sync_state SET status_json=? WHERE id=1',
                               (json.dumps({k:v for k,v in state.items() if k != 'next_run_at'}),))
        board.conn.commit()
        board.reserve_trip_sync_status = state
        return state


def sync_if_due(board, authority_path, evidence_root, url=SOURCE_URL, *, now=None, stop=None):
    """조회 시작 전에 다음 날짜를 저장해 성공·실패·재시작 모두 하루 한 번으로 제한한다."""
    moment = (now or dt.datetime.now(KST)).astimezone(KST)
    with board._lock:
        state = sync_status(board)
        scheduled = dt.datetime.fromisoformat(state['next_run_at'])
        if moment < scheduled or (stop is not None and stop.is_set()):
            return False
        next_run = next_midnight(moment).isoformat()
        started = {'status':'running', 'started_at':moment.isoformat()}
        claimed = board.conn.execute(
            'UPDATE reserve_trip_sync_state SET next_run_at=?,status_json=? WHERE id=1 AND next_run_at=?',
            (next_run, json.dumps(started), state['next_run_at']))
        board.conn.commit()
        if not claimed.rowcount:
            return False
        board.reserve_trip_sync_status = dict(started, next_run_at=next_run)
    try:
        records = fetch_records(url)
        if stop is not None and stop.is_set():
            raise ValueError('RESERVE_SYNC_INTERRUPTED')
        result = sync_records(board, records, authority_path, evidence_root, day=moment.date().isoformat())
    except Exception as exc:
        code = str(exc) if re.fullmatch(r'RESERVE_[A-Z_]+',str(exc)) else type(exc).__name__
        result = {'status':'failed', 'error':code, 'observed_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    with board._lock:
        result = dict(result, started_at=started['started_at'])
        board.conn.execute('UPDATE reserve_trip_sync_state SET status_json=? WHERE id=1',
                           (json.dumps(result),))
        board.conn.commit()
        board.reserve_trip_sync_status = dict(result, next_run_at=next_run)
    return True


def start_sync(board, authority_path, evidence_root, url=SOURCE_URL):
    """같은 작성자 연결에서 한국 시간 매일 0시에 조회한다."""
    initialize_sync_schedule(board)
    stop = threading.Event()
    def loop():
        while not stop.is_set():
            sync_if_due(board, authority_path, evidence_root, url, stop=stop)
            next_run = dt.datetime.fromisoformat(sync_status(board)['next_run_at'])
            delay = (next_run - dt.datetime.now(KST)).total_seconds()
            # 로컬 시계 보정은 반영하되 이 대기 중에는 여행글을 조회하지 않는다.
            stop.wait(min(60, max(0.1, delay)))
    thread = threading.Thread(target=loop,name='reserve-trip-sync',daemon=True)
    thread.start()
    return stop
