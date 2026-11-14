"""모든 OTA의 직접 수집·메일·참고 자료를 원문과 함께 한 DB에서 관리한다."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import zlib
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'ota-store-v1'
MAIL_STAMP_FILE = '.mail-import-stamp.json'
DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS ota_store_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ota_sources(
 source_id TEXT PRIMARY KEY,kind TEXT NOT NULL,locator TEXT NOT NULL,
 ordinal INTEGER NOT NULL,current_revision TEXT,UNIQUE(kind,locator));
CREATE TABLE IF NOT EXISTS ota_source_revisions(
 revision_id TEXT PRIMARY KEY,source_id TEXT REFERENCES ota_sources(source_id),
 sha256 TEXT NOT NULL,observed_at TEXT NOT NULL,UNIQUE(source_id,sha256));
CREATE TABLE IF NOT EXISTS ota_raw_entries(
 revision_id TEXT REFERENCES ota_source_revisions(revision_id),entry_key TEXT,
 payload_json TEXT NOT NULL,PRIMARY KEY(revision_id,entry_key));
CREATE TABLE IF NOT EXISTS ota_raw_blobs(
 sha256 TEXT PRIMARY KEY,payload_json BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS ota_messages(
 message_id TEXT PRIMARY KEY,core_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ota_mail_origins(
 message_id TEXT REFERENCES ota_messages(message_id),source_id TEXT REFERENCES ota_sources(source_id),
 PRIMARY KEY(message_id,source_id));
CREATE TABLE IF NOT EXISTS ota_bookings(
 booking_id TEXT PRIMARY KEY,provider TEXT NOT NULL,account_key TEXT NOT NULL,
 booking_number TEXT NOT NULL,UNIQUE(provider,account_key,booking_number));
CREATE TABLE IF NOT EXISTS ota_booking_evidence(
 booking_id TEXT REFERENCES ota_bookings(booking_id),revision_id TEXT REFERENCES ota_source_revisions(revision_id),
 entry_key TEXT NOT NULL,evidence_kind TEXT NOT NULL,fact_json TEXT NOT NULL,
 PRIMARY KEY(booking_id,revision_id,entry_key));
CREATE TABLE IF NOT EXISTS ota_reservation_observations(
 observation_id TEXT NOT NULL,revision_id TEXT REFERENCES ota_source_revisions(revision_id),
 entry_key TEXT NOT NULL,provider TEXT NOT NULL,booking_ref TEXT,
 source_digest TEXT NOT NULL,fact_json TEXT NOT NULL,
 PRIMARY KEY(observation_id,revision_id,entry_key));
CREATE INDEX IF NOT EXISTS ota_booking_evidence_fact_lookup ON ota_booking_evidence(booking_id,entry_key);
CREATE INDEX IF NOT EXISTS ota_reservation_observations_lookup ON ota_reservation_observations(observation_id,entry_key);
CREATE TABLE IF NOT EXISTS ota_row_seen(
 kind TEXT NOT NULL,owner_id TEXT NOT NULL,entry_key TEXT NOT NULL,home_revision TEXT NOT NULL,
 source_id TEXT NOT NULL,first_revision TEXT NOT NULL,last_revision TEXT NOT NULL,
 first_observed_at TEXT NOT NULL,last_observed_at TEXT NOT NULL,seen_count INTEGER NOT NULL,
 PRIMARY KEY(kind,owner_id,entry_key,home_revision,source_id));
CREATE TABLE IF NOT EXISTS ota_portal_rows(
 revision_id TEXT REFERENCES ota_source_revisions(revision_id),row_no INTEGER,
 payload_json TEXT NOT NULL,PRIMARY KEY(revision_id,row_no));
CREATE TABLE IF NOT EXISTS ota_catalog_rows(
 revision_id TEXT REFERENCES ota_source_revisions(revision_id),row_no INTEGER,
 payload_json TEXT NOT NULL,PRIMARY KEY(revision_id,row_no));
CREATE TABLE IF NOT EXISTS ota_scheduled_rows(
 revision_id TEXT REFERENCES ota_source_revisions(revision_id),row_no INTEGER,
 payload_json BLOB NOT NULL,PRIMARY KEY(revision_id,row_no));
'''


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def encoded_sha256(value):
    """Hash the exact canonical JSON without joining an entire source in memory."""
    from .p2_source_io import checkpoint
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    for fragment in encoder.iterencode(value):
        checkpoint()
        digest.update(fragment.encode('utf-8'))
    return digest.hexdigest()


def packed(value):
    return zlib.compress(encoded(value).encode('utf-8'))


def unpacked(value):
    from .p2_source_io import unpack
    return unpack(value)


def connect_read(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    from .p2_source_io import guard_connection
    guard_connection(conn)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')
    return conn


def is_store(path):
    if not Path(path).is_file():
        return False
    with Path(path).open('rb') as handle:
        if handle.read(16) != b'SQLite format 3\x00':
            return False
    with closing(connect_read(path)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ota_store_meta'").fetchone():
            return False
        row = conn.execute("SELECT value FROM ota_store_meta WHERE key='schema_version'").fetchone()
        if not row or row[0] != SCHEMA:
            raise ValueError('OTA_STORE_SCHEMA_MISMATCH')
        return True


def _current_rows(conn, table, kind):
    return conn.execute('SELECT s.ordinal,s.source_id,r.* FROM ' + table + ' r '
        'JOIN ota_sources s ON s.current_revision=r.revision_id WHERE s.kind=? '
        'ORDER BY s.ordinal,r.row_no', (kind,)).fetchall()


def _entries(conn, revision):
    entries = {row['entry_key']: unpacked(row['payload_json']) for row in conn.execute(
        'SELECT entry_key,payload_json FROM ota_raw_entries WHERE revision_id=?', (revision,))}
    for key, value in entries.items():
        if isinstance(value, dict) and set(value) == {'ota_blob_sha256'}:
            blob = conn.execute('SELECT payload_json FROM ota_raw_blobs WHERE sha256=?',
                                (value['ota_blob_sha256'],)).fetchone()
            if not blob:
                raise ValueError('OTA_STORE_RAW_BLOB_MISSING')
            decoded = unpacked(blob[0])
            if encoded_sha256(decoded) != value['ota_blob_sha256']:
                raise ValueError('OTA_STORE_RAW_HASH_MISMATCH')
            entries[key] = decoded
    expected = conn.execute('SELECT sha256 FROM ota_source_revisions WHERE revision_id=?', (revision,)).fetchone()
    if not expected or encoded_sha256(entries) != expected[0]:
        raise ValueError('OTA_STORE_RAW_HASH_MISMATCH')
    return entries


def portal_rows(path, outer_index, *, scheduled=False):
    with closing(connect_read(path)) as conn:
        source_locators = {row['source_id']: row['locator'] for row in conn.execute(
            "SELECT source_id,locator FROM ota_sources WHERE kind='portal_database'")}
        # 출처별 원래 ID와 그룹 경계를 유지한다. 파일 하나로 합쳐도 숫자 ID를 섞지 않는다.
        table = 'ota_scheduled_rows' if scheduled else 'ota_portal_rows'
        available = conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone()
        if available:
            rows = [{**unpacked(row['payload_json']), 'database':f'{outer_index}:{row["source_id"]}',
                     '_source_locator': source_locators[row['source_id']]}
                    for row in _current_rows(conn, table, 'portal_database')]
            if scheduled:
                for source in conn.execute("SELECT * FROM ota_sources WHERE kind='portal_database' ORDER BY ordinal"):
                    if conn.execute('SELECT 1 FROM ota_scheduled_rows WHERE revision_id=? LIMIT 1',
                                    (source['current_revision'],)).fetchone():
                        continue
                    rows.extend({**row, 'database':f'{outer_index}:{source["source_id"]}'}
                                for row in _scheduled_details(_entries(conn, source['current_revision'])))
        else:
            rows = [{**row, 'database':f'{outer_index}:{source["source_id"]}'}
                    for source in conn.execute("SELECT * FROM ota_sources WHERE kind='portal_database' ORDER BY ordinal")
                    for row in _scheduled_details(_entries(conn, source['current_revision']))]
        for booking, fact, conflicts in direct_facts(conn):
            if booking['provider'] != 'agoda' or fact.get('evidence_format') not in ('agoda-aside-v1', 'agoda-api-v1'):
                continue
            # 새 Aside 양식은 예정일 대사의 입력이 아니다. 명시 취소·환불·충돌은 차단 근거로 유지한다.
            if scheduled and not (conflicts or fact['reservation_status'] in ('cancelled','refunded')
                                  or fact.get('refund_status') not in (None,'none_displayed')):
                continue
            identity = 'aside-v1:' + sha(booking['account_key'])[:16] + ':agoda:' + booking['booking_number']
            for role in fact['roles']:
                rows.append({'booking_number':booking['booking_number'],
                    'service_start_on':fact['service_start_on'], 'service_end_on':fact['service_end_on'],
                    'status':fact['reservation_status'], 'id':identity, 'payload_json':encoded(fact),
                    'source_sha256':sha(encoded(fact)), 'evidence_role':role, 'evidence_status':'observed',
                    'conflict_count':len(conflicts), 'conflict_json':encoded(conflicts),
                    'database':f'{outer_index}:direct'})
        return rows


def catalog_rows(conn):
    rows = [unpacked(row['payload_json']) for row in _current_rows(conn, 'ota_catalog_rows', 'portal_database')]
    rows.extend({'id':booking['booking_id'], 'provider':booking['provider'],
                 'booking_number':booking['booking_number'], 'product_type':fact.get('product_type', 'lodging'),
                 'label':fact.get('label'), 'service_start_on':None if conflicts else fact.get('service_start_on'),
                 'service_end_on':None if conflicts else fact.get('service_end_on'), 'status':fact.get('reservation_status', 'unknown'),
                 'trips':[]} for booking,fact,conflicts in direct_facts(conn))
    for row in conn.execute("SELECT b.*,e.fact_json FROM ota_booking_evidence e JOIN ota_bookings b USING(booking_id) "
        "JOIN ota_sources s ON s.current_revision=e.revision_id WHERE e.evidence_kind='direct_list'"):
        fact = json.loads(row['fact_json'])
        rows.append({'id':row['booking_id'], 'provider':row['provider'], 'booking_number':row['booking_number'],
            'product_type':'unknown', 'label':None, 'service_start_on':None, 'service_end_on':None,
            'status':fact['list_status'], 'trips':[]})
    available = conn.execute("SELECT 1 FROM sqlite_master WHERE name='ota_reservation_observations'").fetchone()
    if available:
        seen = set()
        query = ("SELECT s.ordinal AS ord,o.* FROM ota_reservation_observations o JOIN ota_sources s "
                 "ON s.current_revision=o.revision_id")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='ota_row_seen'").fetchone():
            # 같은 사실은 다시 쓰지 않고 관측 기록만 갱신하므로, 현재 판에서 다시 관측된 행도 현재 행이다.
            query += (" UNION SELECT s.ordinal AS ord,o.* FROM ota_reservation_observations o "
                      "JOIN ota_row_seen z ON z.kind='observation' AND z.owner_id=o.observation_id "
                      "AND z.entry_key=o.entry_key AND z.home_revision=o.revision_id "
                      "JOIN ota_sources s ON s.source_id=z.source_id AND s.current_revision=z.last_revision")
        for row in conn.execute("SELECT * FROM (" + query + ") ORDER BY ord,observation_id,entry_key"):
            if row['observation_id'] in seen:
                continue
            seen.add(row['observation_id'])
            fact = json.loads(row['fact_json'])
            period = fact.get('service_period') or {}
            rows.append(dict(id=row['observation_id'],provider=row['provider'],
                booking_number=row['observation_id'],supplier_booking_ref=row['booking_ref'],
                identity_kind='reservation_observation',product_type='lodging',label=fact.get('item'),
                service_start_on=period.get('starts_on'),service_end_on=period.get('ends_on'),
                status=fact.get('reservation_status','observed'),trips=[]))
    return rows


def _scheduled_details(entries):
    bookings = {row['id']:row['booking_number'] for row in entries['bookings']}
    details = {}
    for evidence in entries.get('booking_source_evidence', []):
        key = (bookings.get(evidence['booking_id']), evidence['direct_source_record_id'], evidence['evidence_role'])
        details.setdefault(key, set()).add(evidence.get('conflict_json'))
    rows = []
    for row in entries['_portal_read_rows']:
        values = details.get((row['booking_number'],row['id'],row['evidence_role']), set())
        rows.append({**row, 'conflict_json':next(iter(values)) if len(values)==1 else None})
    return rows


def direct_facts(conn):
    """관측은 모두 보존하고, 현재 자료의 서로 다른 금액·카드·기간은 보류한다."""
    # Later verified mail cancellation overrides an earlier direct confirmation.
    # It never overwrites the observed payment or refund facts.
    cancellations = {}
    for mail in conn.execute(
        "SELECT b.booking_number,e.entry_key,e.fact_json,m.payload_json "
        "FROM ota_booking_evidence e JOIN ota_bookings b ON b.booking_id=e.booking_id "
        "JOIN ota_messages m ON m.message_id=e.entry_key "
        "WHERE b.provider='agoda' AND e.evidence_kind='mail' "
        "AND e.fact_json LIKE '%\"reservation_status\":\"cancelled\"%'"
    ):
        evidence = json.loads(mail['fact_json'])
        if evidence.get('reservation_status') != 'cancelled':
            continue
        message = unpacked(mail['payload_json'])
        try:
            cancelled_at = datetime.fromtimestamp(
                int(message['internal_date']) / 1000, timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        ref = mail['booking_number']
        if ref not in cancellations or cancelled_at > cancellations[ref][0]:
            cancellations[ref] = (cancelled_at, mail['entry_key'])
    groups = {}
    direct_accounts = {}
    for row in conn.execute("SELECT b.*,e.fact_json,r.observed_at FROM ota_booking_evidence e "
        "JOIN ota_bookings b USING(booking_id) "
        "JOIN ota_source_revisions r ON r.revision_id=e.revision_id WHERE e.evidence_kind='direct'"):
        fact = json.loads(row['fact_json'])
        groups.setdefault(row['booking_id'], []).append((dict(row), fact))
        direct_accounts.setdefault((row['provider'], row['booking_number']), set()).add(row['account_key'])
    result = []
    for observations in groups.values():
        observations.sort(key=lambda item:(item[1].get('observed_at') or item[0]['observed_at'],
            item[1].get('parser_version') if isinstance(item[1].get('parser_version'),int) else 0, encoded(item[1])))
        conflicts = []
        for field in ('service_start_on', 'service_end_on', 'card_last4'):
            values = {fact.get(field) for _,fact in observations} - {None, ''}
            if len(values) > 1:
                conflicts.append(field)
        amounts = {encoded(sorted((part['currency'],part['decimal_text'])
                   for part in fact.get('price_components', []) if part['kind']=='paid_today'))
                   for _,fact in observations if any(part['kind']=='paid_today' for part in fact.get('price_components', []))}
        if len(amounts) > 1:
            conflicts.append('paid_amount')
        terminal = False
        for _, fact in observations:
            if terminal and fact.get('reservation_status') in ('confirmed', 'completed'):
                conflicts.append('active_after_cancellation')
            terminal |= fact.get('reservation_status') == 'cancelled'
        row, fact = observations[-1]
        cancellation = cancellations.get(row['booking_number']) if row['provider'] == 'agoda' else None
        if cancellation:
            cancellation_at, message_id = cancellation
            if len(direct_accounts[('agoda', row['booking_number'])]) > 1:
                conflicts.append('cancellation_account_ambiguous')
            else:
                last_seen = fact.get('observed_at') or row['observed_at']
                try:
                    seen_at = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    if seen_at.utcoffset() is None:
                        seen_at = None
                    else:
                        seen_at = seen_at.astimezone(timezone.utc)
                except (AttributeError, TypeError, ValueError):
                    seen_at = None
                if seen_at is None:
                    conflicts.append('cancellation_chronology_unknown')
                elif seen_at > cancellation_at and fact.get('reservation_status') != 'cancelled':
                    conflicts.append('active_after_cancellation')
                elif seen_at <= cancellation_at:
                    fact = {**fact, 'reservation_status':'cancelled',
                        'cancellation_mail_message_id':message_id,
                        'cancellation_mail_observed_at':cancellation_at.isoformat()}
        result.append((row, fact, conflicts))
    return result


def mail_bundles(path):
    return list(iter_mail_bundles(path))


def iter_mail_bundles(path):
    """Verify and release one source scope at a time, retaining legacy ordering."""
    with closing(connect_read(path)) as conn:
        for source in conn.execute("SELECT * FROM ota_sources WHERE kind='mail_directory' ORDER BY ordinal"):
            entries = _entries(conn, source['current_revision'])
            collection = {key:value for key,value in entries.get('collection', {}).items()
                          if key in ('after', 'before', 'query_exhausted', 'fetched')}
            messages = [message for key in sorted(entries) if key.startswith('gmail') and key.endswith('.json')
                        for message in entries[key]['responses']]
            del entries
            yield source['locator'], collection, messages


def reference_bundles(path):
    with closing(connect_read(path)) as conn:
        for row in conn.execute("SELECT * FROM ota_sources WHERE kind='reference_document' ORDER BY ordinal"):
            yield row['locator'], _entries(conn, row['current_revision'])['raw']


class OtaStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if self.path.exists() and self.path.stat().st_size and not is_store(self.path):
            raise ValueError('OTA_STORE_REFUSE_UNRELATED_DATABASE')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.row_factory = sqlite3.Row
        self._fact_cache = {}
        self.conn.executescript(DDL)
        current = self.conn.execute("SELECT value FROM ota_store_meta WHERE key='schema_version'").fetchone()
        if current and current[0] != SCHEMA:
            self.conn.close()
            raise ValueError('OTA_STORE_SCHEMA_MISMATCH')
        with self.conn:
            self.conn.execute('INSERT OR IGNORE INTO ota_store_meta VALUES(?,?)', ('schema_version', SCHEMA))

    def close(self):
        self.conn.close()

    @contextmanager
    def atomic(self):
        if self.conn.in_transaction:
            self.conn.execute('SAVEPOINT ota_import')
            try:
                yield
                self.conn.execute('RELEASE ota_import')
            except BaseException:
                self.conn.execute('ROLLBACK TO ota_import')
                self.conn.execute('RELEASE ota_import')
                raise
        else:
            with self.conn:
                yield

    def _revision(self, kind, locator, entries):
        locator = str(locator) if kind == 'direct_observation' else str(Path(locator).resolve())
        identity = sha(encoded([kind, locator]))
        digest = sha(encoded(entries))
        revision = sha(encoded([identity, digest]))
        ordinal = self.conn.execute('SELECT coalesce(max(ordinal),-1)+1 FROM ota_sources').fetchone()[0]
        self.conn.execute('INSERT OR IGNORE INTO ota_sources VALUES(?,?,?,?,NULL)',
                          (identity, kind, locator, ordinal))
        inserted = self.conn.execute('INSERT OR IGNORE INTO ota_source_revisions VALUES(?,?,?,?)',
            (revision, identity, digest, datetime.now(timezone.utc).isoformat())).rowcount
        if inserted:
            for key, value in entries.items():
                content_sha = sha(encoded(value))
                self.conn.execute('INSERT OR IGNORE INTO ota_raw_blobs VALUES(?,?)', (content_sha, packed(value)))
                self.conn.execute('INSERT INTO ota_raw_entries VALUES(?,?,?)',
                    (revision, key, encoded({'ota_blob_sha256':content_sha})))
        self.conn.execute('UPDATE ota_sources SET current_revision=? WHERE source_id=? AND current_revision IS NOT ?',
                          (revision, identity, revision))
        return identity, revision, bool(inserted)

    def _evidence(self, provider, ref, revision, key, kind, fact, account='legacy-owner'):
        if not provider or not ref:
            return
        identity = sha(encoded([provider, account, str(ref)]))
        self.conn.execute('INSERT OR IGNORE INTO ota_bookings VALUES(?,?,?,?)',
                          (identity, provider, account, str(ref)))
        payload = encoded(fact)
        if kind == 'mail' and self._seen_ready():
            if self._seen_in_revision('evidence', identity, key, revision):
                return
            # 같은 예약·메일·사실이 이미 있으면 새 행 없이 관측 기록만 남긴다.
            old = self.conn.execute('SELECT revision_id FROM ota_booking_evidence WHERE booking_id=? '
                "AND entry_key=? AND evidence_kind='mail' AND fact_json=? ORDER BY rowid LIMIT 1",
                (identity, key, payload)).fetchone()
            if old:
                self._seen('evidence', identity, key, old[0], revision)
                return
        if self.conn.execute('INSERT OR IGNORE INTO ota_booking_evidence VALUES(?,?,?,?,?)',
                             (identity, revision, key, kind, payload)).rowcount and kind == 'mail' and self._seen_ready():
            self._seen('evidence', identity, key, revision, revision)

    def _seen_ready(self):
        return bool(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='ota_row_seen'").fetchone())

    def _seen_in_revision(self, kind, owner, key, revision):
        """같은 판에서 이미 관측했고 그 원래 행이 남아 있으면 사실이 달라져도 다시 쓰지 않는다.

        같은 판 재실행은 첫 사실을 유지하던 종전 의미와 같다. 원래 행이 지워졌으면 다시 만든다.
        """
        table, column = (('ota_booking_evidence', 'booking_id') if kind == 'evidence'
                         else ('ota_reservation_observations', 'observation_id'))
        return bool(self.conn.execute('SELECT 1 FROM ota_row_seen z JOIN ota_source_revisions r '
            'ON r.source_id=z.source_id JOIN ' + table + ' t ON t.' + column + '=z.owner_id '
            'AND t.entry_key=z.entry_key AND t.revision_id=z.home_revision '
            'WHERE z.kind=? AND z.owner_id=? AND z.entry_key=? AND z.last_revision=? AND r.revision_id=?',
            (kind, owner, key, revision, revision)).fetchone())

    def _seen(self, kind, owner, key, home, revision):
        """저장된 행(home 판)을 revision 판에서 관측했다는 사실만 남긴다."""
        if not self._seen_ready():
            return
        source, observed = self.conn.execute(
            'SELECT source_id,observed_at FROM ota_source_revisions WHERE revision_id=?', (revision,)).fetchone()
        if self.conn.execute('UPDATE ota_row_seen SET last_revision=?,last_observed_at=?,seen_count=seen_count+1 '
                'WHERE kind=? AND owner_id=? AND entry_key=? AND home_revision=? AND source_id=? '
                'AND last_revision<>?', (revision, observed, kind, owner, key, home, source, revision)).rowcount:
            return
        if home == revision:
            first, first_at = revision, observed
        else:
            first, first_at = home, self.conn.execute(
                'SELECT observed_at FROM ota_source_revisions WHERE revision_id=?', (home,)).fetchone()[0]
        self.conn.execute('INSERT OR IGNORE INTO ota_row_seen VALUES(?,?,?,?,?,?,?,?,?,?)',
            (kind, owner, key, home, source, first, revision, first_at, observed,
             1 if home == revision else 2))

    @staticmethod
    def mail_stamp(directory):
        """gmail*.json 원문 목록의 파일 이름·크기·mtime과 해석 코드 stat. collection.json은 실행마다 바뀌어 제외한다."""
        code = Path(__file__).resolve().parent
        stamp = [[p.name, p.stat().st_size, p.stat().st_mtime_ns] for p in sorted(Path(directory).glob('gmail*.json'))]
        stamp += [['code:' + n, (code / n).stat().st_size, (code / n).stat().st_mtime_ns]
                  for n in ('ota_store.py', 'ota_mail.py', 'ota_payments.py', 'forest_mail.py')]
        return stamp

    def _mail_stamp_state(self, directory, stamp):
        row = self.conn.execute('SELECT current_revision FROM ota_sources WHERE source_id=?',
            (sha(encoded(['mail_directory', str(Path(directory).resolve())])),)).fetchone()
        return {'database': str(self.path), 'revision': row[0] if row else None, 'stamp': stamp}

    def mail_unchanged(self, directory, stamp):
        """마지막으로 성공한 import 뒤 원문 파일이 달라지지 않았고 DB의 현재 판도 그대로인지 stat·한 행 조회로 판정한다."""
        try:
            saved = json.loads((Path(directory) / MAIL_STAMP_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        return saved == self._mail_stamp_state(directory, stamp) and saved['revision'] is not None

    def record_mail_stamp(self, directory, stamp):
        """commit 뒤에 부른다. 쓰기에 실패하면 다음 실행이 다시 import할 뿐이다."""
        target = Path(directory) / MAIL_STAMP_FILE
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._mail_stamp_state(directory, stamp)), encoding='utf-8')
        os.replace(temporary, target)

    def import_mail(self, directory):
        from app import ota_mail, ota_payments
        messages, inventory = ota_mail.load_messages_from([directory])
        if any(row.get('error') for row in inventory):
            raise ValueError('OTA_STORE_MAIL_INCOMPLETE')
        files = {p.name: json.loads(p.read_text(encoding='utf-8'))
                 for p in sorted(Path(directory).glob('gmail*.json'))}
        collection_path = Path(directory) / 'collection.json'
        files['collection'] = json.loads(collection_path.read_text(encoding='utf-8')) if collection_path.is_file() else {}
        with self.atomic():
            source, revision, inserted = self._revision('mail_directory', directory, files)
            normalized = self.index_reservation_observations(messages, revision)
            if not inserted:
                return bool(normalized)
            for message_id, message in messages.items():
                core = dict(id=message_id, internal_date=message.get('internal_date'),
                    headers={h['name'].lower(): h['value'] for h in message['payload'].get('headers', [])},
                    text=ota_mail.body_text(message['payload']))
                digest = ota_mail._core_digest(core)
                old = self.conn.execute('SELECT core_sha256, payload_json FROM ota_messages WHERE message_id=?',
                                        (message_id,)).fetchone()
                # The stored digest omits a REST-only receipt time, so an equal digest alone is not enough there.
                if old and (old[0] != digest or ota_mail.needs_original_comparison(core, message)):
                    kept = unpacked(old[1])
                    kept_core = dict(id=message_id, internal_date=kept.get('internal_date'),
                        headers={h['name'].lower(): h['value'] for h in kept['payload'].get('headers', [])},
                        text=ota_mail.body_text(kept['payload']))
                    if not ota_mail.same_original_core((kept_core, kept), (core, message)):
                        raise ValueError('OTA_MESSAGE_CONTENT_CONFLICT')
                self.conn.execute('INSERT OR IGNORE INTO ota_messages VALUES(?,?,?)',
                                  (message_id, digest, packed(message)))
                self.conn.execute('INSERT OR IGNORE INTO ota_mail_origins VALUES(?,?)', (message_id, source))
                fact_key = sha(encoded(message))
                if fact_key not in self._fact_cache:
                    self._fact_cache[fact_key] = ota_payments.extract_payment_fact(message)
                fact = self._fact_cache[fact_key]
                if fact:
                    self._evidence(fact['provider'], fact['booking_ref'], revision, message_id, 'mail', fact)
        return inserted

    def index_reservation_observations(self, messages, revision):
        """Add source-specific reservation observations without manufacturing booking numbers."""
        from app import forest_mail
        inserted = 0
        for event in forest_mail.collect(messages):
            key = forest_mail.catalog_reference(event)
            source_id, = event['source_ids']
            entry, payload = source_id.removeprefix('mail:'), encoded(event)
            if self._seen_ready():
                if self._seen_in_revision('observation', key, entry, revision):
                    continue
                source = self.conn.execute('SELECT source_id FROM ota_source_revisions WHERE revision_id=?',
                                           (revision,)).fetchone()[0]
                old = self.conn.execute('SELECT o.revision_id FROM ota_reservation_observations o '
                    'JOIN ota_source_revisions r ON r.revision_id=o.revision_id WHERE o.observation_id=? '
                    'AND o.entry_key=? AND o.fact_json=? AND r.source_id=? ORDER BY o.rowid LIMIT 1',
                    (key, entry, payload, source)).fetchone()
                if old:
                    self._seen('observation', key, entry, old[0], revision)
                    continue
            added = self.conn.execute('INSERT OR IGNORE INTO ota_reservation_observations '
                'VALUES(?,?,?,?,?,?,?)',(key,revision,entry,event['provider'],
                event.get('booking_ref'),event['source_digest'],payload)).rowcount
            if added:
                self._seen('observation', key, entry, revision, revision)
            inserted += added
        return inserted

    def rebuild_reservation_observations(self):
        """Explicit additive reindex of preserved current mail revisions; raw inputs stay intact."""
        inserted = 0
        with self.atomic():
            for source in self.conn.execute("SELECT current_revision FROM ota_sources WHERE kind='mail_directory' ORDER BY ordinal").fetchall():
                revision = source['current_revision']
                entries = _entries(self.conn,revision)
                messages = {m['id']:m for key,value in entries.items() if key.startswith('gmail') and key.endswith('.json')
                            for m in value['responses']}
                inserted += self.index_reservation_observations(messages,revision)
        return inserted

    def import_portal(self, path):
        from app import ota_portal
        if is_store(path):
            raise ValueError('OTA_STORE_RECURSIVE_IMPORT')
        with closing(connect_read(path)) as original:
            tables = {r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            names = ('bookings', 'direct_source_records', 'booking_source_evidence',
                     'booking_target_links', 'allocation_targets', 'capture_pages',
                     'source_observations', 'portal_projection', 'capture_meta')
            entries = {name: [dict(row) for row in original.execute('SELECT * FROM "' + name + '"')]
                       for name in names if name in tables}
            if 'bookings' not in entries:
                raise ValueError('OTA_STORE_BOOKINGS_REQUIRED')
            links = {}
            if {'booking_target_links', 'allocation_targets'} <= tables:
                for row in original.execute("SELECT l.booking_id,t.code,t.name FROM booking_target_links l "
                    "JOIN allocation_targets t ON t.id=l.target_id WHERE l.link_status IN ('confirmed','legacy') "
                    "AND t.target_type='trip'"):
                    links.setdefault(row[0], []).append({'id': row[1], 'name': row[2] or row[1]})
            # 기존 SQL과 같은 원문·근거 행을 하나의 일관된 읽기 트랜잭션에서 보존한다.
            rows = [dict(row) for row in original.execute(
                "SELECT b.booking_number,b.service_start_on,b.service_end_on,b.status,"
                "d.id,d.payload_json,d.source_sha256,e.evidence_role,e.evidence_status,e.conflict_count "
                "FROM bookings b JOIN booking_source_evidence e ON e.booking_id=b.id "
                "JOIN direct_source_records d ON d.id=e.direct_source_record_id "
                "WHERE b.provider='agoda' AND d.source_kind='agoda_portal_detail'")]
            entries['_portal_read_rows'] = rows
            catalog = [{**{key: row.get(key) for key in ('id', 'provider', 'booking_number', 'product_type',
                       'label', 'service_start_on', 'service_end_on', 'status')}, 'trips': links.get(row['id'], [])}
                       for row in entries['bookings']]
            entries['_catalog_read_rows'] = catalog
        with self.atomic():
            source, revision, inserted = self._revision('portal_database', path, entries)
            if inserted:
                self.conn.executemany('INSERT INTO ota_portal_rows VALUES(?,?,?)',
                                      [(revision, n, packed(row)) for n, row in enumerate(rows)])
                self.conn.executemany('INSERT INTO ota_catalog_rows VALUES(?,?,?)',
                                      [(revision, n, packed(row)) for n, row in enumerate(catalog)])
                self.conn.executemany('INSERT INTO ota_scheduled_rows VALUES(?,?,?)',
                    [(revision, n, packed(row)) for n, row in enumerate(_scheduled_details(entries))])
                for n, row in enumerate(entries['bookings']):
                    self._evidence(row['provider'], row['booking_number'], revision,
                                   'bookings:' + str(n), 'portal', row)
        return inserted

    def rebuild_scheduled_index(self):
        """기존 통합 DB의 보존 원문에서 예정일 대사 조회용 행을 한 번 만든다."""
        with self.atomic():
            for row in self.conn.execute("SELECT current_revision FROM ota_sources WHERE kind='portal_database'"):
                revision = row[0]
                if self.conn.execute('SELECT 1 FROM ota_scheduled_rows WHERE revision_id=? LIMIT 1', (revision,)).fetchone():
                    continue
                entries = _entries(self.conn, revision)
                self.conn.executemany('INSERT INTO ota_scheduled_rows VALUES(?,?,?)',
                    [(revision, n, packed(item)) for n, item in enumerate(_scheduled_details(entries))])

    def import_reference(self, path):
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
        with self.atomic():
            return self._revision('reference_document', path, {'raw': raw})[2]

    def import_capture(self, path):
        from app.agoda_capture import parse_detail, utc
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
        if raw.get('schema_version') != 'agoda-aside-capture-v1':
            raise ValueError('OTA_STORE_CAPTURE_SCHEMA')
        if '# note: interactive' in raw.get('snapshot_text', ''):
            raise ValueError('CAPTURE_FULL_SNAPSHOT_REQUIRED')
        utc(raw['observed_at'])
        if not raw.get('account_key') or not raw.get('snapshot_text'):
            raise ValueError('CAPTURE_ACCOUNT_OR_SNAPSHOT_REQUIRED')
        if raw.get('kind') == 'list':
            actual = re.findall(r'heading "ID (\d{6,20})"', raw['snapshot_text'])
            numbers = raw.get('booking_numbers')
            if (not isinstance(numbers, list) or sorted(actual) != sorted(numbers)
                    or len(actual) != len(set(actual))):
                raise ValueError('CAPTURE_LIST_IDENTITY_MISMATCH')
            if (raw.get('list_status') not in ('upcoming', 'completed', 'cancelled')
                    or not isinstance(raw.get('next_disabled'), bool)):
                raise ValueError('CAPTURE_LIST_STATUS_INVALID')
        with self.atomic():
            _, revision, inserted = self._revision('direct_capture', path, {'raw': raw})
            if raw.get('kind') == 'detail':
                fact = parse_detail(raw)
                self._evidence('agoda', fact['booking_number'], revision,
                               'detail:v' + str(fact['parser_version']), 'direct', fact,
                               raw['account_key'])
            elif raw.get('kind') == 'list':
                for ref in raw['booking_numbers']:
                    self._evidence('agoda', ref, revision, str(ref), 'direct_list',
                                   {'list_status': raw['list_status']}, raw['account_key'])
            else:
                raise ValueError('OTA_STORE_CAPTURE_KIND')
        return inserted

    def import_direct(self, *, provider, account_key, source_key, snapshot, facts):
        """공급자별 수집기가 쓰는 공통 진입점. 원문·판단을 보존하고 결제를 만들어내지 않는다."""
        if provider not in ('agoda', 'trip', 'booking', 'klook', 'forest') or not account_key or not source_key:
            raise ValueError('OTA_STORE_DIRECT_IDENTITY_REQUIRED')
        for fact in facts:
            if fact.get('provider') != provider or not fact.get('booking_number'):
                raise ValueError('OTA_STORE_DIRECT_FACT_IDENTITY_MISMATCH')
        with self.atomic():
            _, revision, inserted = self._revision('direct_observation',
                'direct/' + provider + '/' + sha(encoded([account_key, source_key])),
                {'snapshot':snapshot, 'facts':facts, 'account_key':account_key, 'source_key':source_key})
            for n, fact in enumerate(facts):
                self._evidence(provider, fact['booking_number'], revision, str(n), 'direct', fact, account_key)
        return inserted

    def summary(self):
        tables = ('ota_sources', 'ota_source_revisions', 'ota_raw_entries', 'ota_raw_blobs', 'ota_messages',
                  'ota_bookings', 'ota_booking_evidence', 'ota_portal_rows', 'ota_catalog_rows',
                  'ota_reservation_observations', 'ota_row_seen')
        return {table: self.conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in tables}
